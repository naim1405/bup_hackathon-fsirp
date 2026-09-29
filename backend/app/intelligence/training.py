"""In-memory model bootstrap from simulator-owned demand history.

Demand history is fetched from the simulator during bootstrap and retained only
in the running process for online updates. It is not copied into a local file,
database, or second history API. After a backend restart, the engine bootstraps
again from the simulator's own ``/v1/demand-history`` endpoint.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.intelligence.config import PolicyConfig
from app.intelligence.forecaster import DemandModel, SeriesKey
from app.intelligence.models import TrainingStatus
from app.intelligence.snapshot import WorldContext
from app.simulator.models import DemandObservation, Station

logger = logging.getLogger(__name__)
_MAX_ROWS_PER_SERIES = 4000


@dataclass
class BootstrapReport:
    stations_fetched: int
    rows_collected: int
    rows_after_dedup: int
    elapsed_ms: float
    errors: list[str]


def merge_demand_rows(
    rows: list[DemandObservation],
    history: dict[SeriesKey, list[tuple[int, float]]],
) -> int:
    """Merge simulator observations into process memory, deduplicated by tick."""
    added = 0
    for row in rows:
        key: SeriesKey = (row.station_id, row.fuel_type.value)
        series = history.setdefault(key, [])
        known = {tick for tick, _ in series}
        if row.tick in known:
            continue
        series.append((row.tick, row.demand_liters))
        if len(series) > _MAX_ROWS_PER_SERIES:
            del series[: len(series) - _MAX_ROWS_PER_SERIES]
        added += 1
    return added


async def bootstrap_model(
    policy: PolicyConfig,
    world: WorldContext,
    stations: list[Station],
    fetch_history: Callable[[str, int], Awaitable[list[DemandObservation]]],
    *,
    known_history: dict[SeriesKey, list[tuple[int, float]]] | None = None,
    now_tick: int,
) -> tuple[DemandModel, BootstrapReport]:
    """Fetch per-station source history and fit a fresh in-memory model."""
    started = time.monotonic()
    history = known_history if known_history is not None else {}
    collected = 0
    errors: list[str] = []
    for station in stations:
        try:
            observations = await fetch_history(station.id, policy.bootstrap_demand_limit)
            collected += len(observations)
            merge_demand_rows(observations, history)
        except Exception as exc:  # noqa: BLE001 — one bad station must not kill training
            errors.append(station.id)
            logger.warning("Demand history fetch failed for station %s: %s", station.id, exc)

    model = DemandModel(policy=policy, world=world)
    rows_after = sum(len(values) for values in history.values())
    model.fit_full(history, now_tick=now_tick)
    report = BootstrapReport(
        stations_fetched=len(stations),
        rows_collected=collected,
        rows_after_dedup=rows_after,
        elapsed_ms=round((time.monotonic() - started) * 1000, 1),
        errors=errors,
    )
    logger.info(
        "Intelligence bootstrap: %d rows for %d series in %.0fms (%d fetch errors)",
        report.rows_after_dedup,
        len(history),
        report.elapsed_ms,
        len(errors),
    )
    return model, report


def training_status(model: DemandModel | None, message: str = "") -> TrainingStatus:
    """Summarize trained-model state for the status endpoint."""
    if model is None:
        return TrainingStatus(
            trained=False, samples=0, message=message or "No trained model loaded."
        )
    fuels = list(model.ridge.values())
    samples = max((ridge.samples for ridge in fuels), default=0)
    last_tick = max(
        (ridge.last_trained_tick for ridge in fuels if ridge.last_trained_tick is not None),
        default=None,
    )
    last_epoch = max(
        (
            ridge.last_trained_at_epoch
            for ridge in fuels
            if ridge.last_trained_at_epoch is not None
        ),
        default=None,
    )
    mae_pair = next(
        (pair for ridge in fuels if (pair := ridge.recent_mae()) is not None), None
    )
    improvement = None
    if mae_pair is not None and mae_pair[1] > 0:
        improvement = round(1.0 - mae_pair[0] / mae_pair[1], 4)
    weights_present = any(ridge.weights is not None for ridge in fuels)
    return TrainingStatus(
        trained=weights_present and samples > 0,
        samples=samples,
        last_trained_tick=last_tick,
        last_trained_at_epoch=last_epoch,
        validation_mae_liters=round(mae_pair[0], 2) if mae_pair else None,
        baseline_mae_liters=round(mae_pair[1], 2) if mae_pair else None,
        improvement_vs_baseline=improvement,
        message=message
        or (
            "Trained model active."
            if weights_present
            else "Training data accumulated; ridge not solved yet."
        ),
    )
