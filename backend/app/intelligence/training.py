"""History persistence and the bootstrap training pipeline.

The engine trains from the simulator's own historical data:

1. **Bootstrap** — on first contact with a run, fetch each station's demand
   history (``GET /v1/demand-history?station_id=…&limit=…``), normalize it to
   per-series ``(tick, liters)`` rows, deduplicate by tick, and batch-fit the
   demand model (seasonal profile + EWMA + pooled ridge per fuel).
2. **Continuous learning** — the background loop appends new demand rows as
   ticks complete, updates the model online (prequential: the forecast for a
   tick is always recorded *before* the observation is learned), and
   periodically re-solves the ridge weights.
3. **Persistence** — raw history and trained model state are stored as JSON
   under ``INTELLIGENCE_HISTORY_DIR`` (default ``var/intelligence``), keyed by
   simulation run id, so restarts keep learning state and a simulator reset
   (new run id) cleanly isolates the new history.

There is no pickle and no binary state: everything is inspectable JSON.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.intelligence.config import PolicyConfig
from app.intelligence.forecaster import DemandModel, SeriesKey
from app.intelligence.models import TrainingStatus
from app.intelligence.snapshot import WorldContext
from app.simulator.models import DemandObservation, Station

logger = logging.getLogger(__name__)

_HISTORY_VERSION = 1
_MAX_ROWS_PER_SERIES = 4000


@dataclass
class BootstrapReport:
    stations_fetched: int
    rows_collected: int
    rows_after_dedup: int
    elapsed_ms: float
    errors: list[str]


class IntelligenceStore:
    """JSON persistence for demand history and trained model state."""

    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    # -- paths ----------------------------------------------------------------

    def _history_path(self, run_id: str) -> str:
        safe = run_id.replace(":", "_").replace("/", "_")
        return os.path.join(self.base_dir, f"history_{safe}.json")

    def _model_path(self, run_id: str) -> str:
        safe = run_id.replace(":", "_").replace("/", "_")
        return os.path.join(self.base_dir, f"model_{safe}.json")

    # -- history ----------------------------------------------------------------

    def load_history(self, run_id: str) -> dict[SeriesKey, list[tuple[int, float]]]:
        path = self._history_path(run_id)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
            if payload.get("version") != _HISTORY_VERSION:
                return {}
            out: dict[SeriesKey, list[tuple[int, float]]] = {}
            for compound, rows in payload.get("series", {}).items():
                station, fuel = compound.split("|", 1)
                out[(station, fuel)] = [(int(t), float(d)) for t, d in rows]
            return out
        except (json.JSONDecodeError, OSError, ValueError, KeyError):
            logger.exception("Failed to load intelligence history from %s", path)
            return {}

    def save_history(self, run_id: str, history: dict[SeriesKey, list[tuple[int, float]]]) -> None:
        path = self._history_path(run_id)
        tmp = path + ".tmp"
        payload = {
            "version": _HISTORY_VERSION,
            "updated_at_epoch": time.time(),
            "series": {
                f"{station}|{fuel}": [
                    [tick, demand]
                    for tick, demand in sorted(rows)[- _MAX_ROWS_PER_SERIES:]
                ]
                for (station, fuel), rows in history.items()
            },
        }
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        os.replace(tmp, path)

    def append_rows(
        self,
        run_id: str,
        rows: list[DemandObservation],
        history: dict[SeriesKey, list[tuple[int, float]]],
    ) -> int:
        """Merge new observations into the in-memory history; returns added count."""
        added = 0
        for row in rows:
            key: SeriesKey = (row.station_id, row.fuel_type.value)
            series = history.setdefault(key, [])
            known = {t for t, _ in series}
            if row.tick in known:
                continue
            series.append((row.tick, row.demand_liters))
            if len(series) > _MAX_ROWS_PER_SERIES * 2:
                del series[: len(series) - _MAX_ROWS_PER_SERIES]
            added += 1
        if added:
            self.save_history(run_id, history)
        return added

    # -- model state -------------------------------------------------------------

    def save_model(self, run_id: str, model: DemandModel) -> None:
        path = self._model_path(run_id)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(model.to_json())
        os.replace(tmp, path)

    def load_model(
        self, run_id: str, policy: PolicyConfig, world: WorldContext
    ) -> DemandModel | None:
        path = self._model_path(run_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
            model = DemandModel(policy=policy, world=world)
            if model.load_json(raw):
                return model
        except OSError:
            logger.exception("Failed to load trained model from %s", path)
        return None


async def bootstrap_model(
    store: IntelligenceStore,
    run_id: str,
    policy: PolicyConfig,
    world: WorldContext,
    stations: list[Station],
    fetch_history: Callable[[str, int], Awaitable[list[DemandObservation]]],
    known_history: dict[SeriesKey, list[tuple[int, float]]] | None = None,
) -> tuple[DemandModel, BootstrapReport]:
    """Fetch historical demand for every station and batch-fit a fresh model.

    ``fetch_history(station_id, limit)`` must call the simulator's
    ``/v1/demand-history`` endpoint. History is merged with any rows already
    persisted for this run so repeated bootstraps are cheap and idempotent.
    """
    started = time.monotonic()
    history: dict[SeriesKey, list[tuple[int, float]]] = known_history or {}
    collected = 0
    errors: list[str] = []
    for station in stations:
        try:
            observations = await fetch_history(station.id, policy.bootstrap_demand_limit)
            collected += len(observations)
            store.append_rows(run_id, observations, history)
        except Exception as exc:  # noqa: BLE001 — one bad station must not kill training
            errors.append(f"{station.id}: {exc}")
            logger.warning("Demand history fetch failed for %s: %s", station.id, exc)

    model = DemandModel(policy=policy, world=world)
    rows_after = sum(len(v) for v in history.values())
    model.fit_full(history, now_tick=0)
    report = BootstrapReport(
        stations_fetched=len(stations),
        rows_collected=collected,
        rows_after_dedup=rows_after,
        elapsed_ms=round((time.monotonic() - started) * 1000, 1),
        errors=errors,
    )
    logger.info(
        "Intelligence bootstrap: %d rows for %d series in %.0fms (%d errors)",
        report.rows_after_dedup,
        len(history),
        report.elapsed_ms,
        len(errors),
    )
    store.save_model(run_id, model)
    return model, report


def training_status(model: DemandModel | None, message: str = "") -> TrainingStatus:
    """Summarize trained-model state for the status endpoint."""
    if model is None:
        return TrainingStatus(
            trained=False, samples=0, message=message or "No trained model loaded."
        )
    fuels = list(model.ridge.values())
    samples = max((r.samples for r in fuels), default=0)
    last_tick = max((r.last_trained_tick for r in fuels if r.last_trained_tick is not None), default=None)
    last_epoch = max(
        (r.last_trained_at_epoch for r in fuels if r.last_trained_at_epoch is not None),
        default=None,
    )
    mae_pair = None
    for ridge in fuels:
        pair = ridge.recent_mae()
        if pair is not None:
            mae_pair = pair
            break
    improvement = None
    if mae_pair is not None and mae_pair[1] > 0:
        improvement = round(1.0 - mae_pair[0] / mae_pair[1], 4)
    weights_present = any(r.weights is not None for r in fuels)
    return TrainingStatus(
        trained=weights_present and samples > 0,
        samples=samples,
        last_trained_tick=last_tick,
        last_trained_at_epoch=last_epoch,
        validation_mae_liters=round(mae_pair[0], 2) if mae_pair else None,
        baseline_mae_liters=round(mae_pair[1], 2) if mae_pair else None,
        improvement_vs_baseline=improvement,
        message=message or ("Trained model active." if weights_present else "Training data accumulated; ridge not solved yet."),
    )


def describe_run(store: IntelligenceStore) -> dict[str, Any]:
    """List persisted artifacts (for the status/debug endpoint)."""
    files = sorted(os.listdir(store.base_dir)) if os.path.isdir(store.base_dir) else []
    return {"history_dir": store.base_dir, "artifacts": files}
