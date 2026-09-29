"""Demand forecasting: trained pooled ridge model + seasonal/EWMA ensemble.

Design (matches docs/recommendation-engine-design.md step B and the team's
"pure-Python trained model" choice):

* **Seasonal profile** per (station, fuel): robust median of demand observed at
  the same tick-of-day, shrunk toward the documented profile prior until
  enough cycles exist.
* **EWMA level ratio**: exponential moving average of ``demand / profile``
  that captures recent level shifts (events, demand spikes) quickly.
* **Trained model**: one regularized online linear (ridge) regression per fuel
  type, pooled across stations. Features: station scale, region factor, live
  demand multiplier, Fourier terms of the tick-of-day, lag-1/lag-season
  demand, and the EWMA ratio. It is trained with weight decay by closed-form
  accumulation (``A = A·decay + x·xᵀ``, ``b = b·decay + x·y``) — no external
  ML dependencies.
* **Ensembling**: the trained model only adjusts the *level* of the seasonal
  path (its next-tick opinion is blended in at ``trained_model_weight`` and
  the adjustment decays over the horizon). The trained model is promoted only
  when it has enough samples AND its recent one-step MAE beats the untrained
  ensemble (prequential evaluation); otherwise the engine falls back.
* **Uncertainty**: empirical p10/p90 from stored *prequential* residuals
  (forecast issued before the tick it predicts), pooled per horizon bucket
  when a single horizon has too few samples. No fabricated probabilities.

Everything is deterministic and JSON-serializable so training state survives
restarts and can be unit-tested offline.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.intelligence import priors
from app.intelligence.config import PolicyConfig

SeriesKey = tuple[str, str]  # (station_id, fuel_type)

_ONE_STEP_ERROR_CAP = 240
_PENDING_MAX_AGE_TICKS = 400
_OBS_KEEP_TICKS_FACTOR = 4  # keep this many seasons of raw observations
_PROFILE_BUCKET_CAP = 32
_QUANTILE_MIN_SAMPLES = 30
_ERROR_BUCKETS: tuple[tuple[int, int], ...] = ((1, 3), (4, 8), (9, 16), (17, 24))


# ---------------------------------------------------------------------------
# Small numeric helpers (numpy-free on purpose)
# ---------------------------------------------------------------------------


def _quantile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated quantile of an already-sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return sorted_values[int(pos)]
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (pos - low)


def _solve_linear(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting. Returns None if singular."""
    n = len(rhs)
    aug = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot_row][col]) < 1e-10:
            return None
        aug[col], aug[pivot_row] = aug[pivot_row], aug[col]
        pivot = aug[col][col]
        for r in range(n + 1):
            aug[col][r] /= pivot
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col]
            if factor == 0.0:
                continue
            for c in range(col, n + 1):
                aug[r][c] -= factor * aug[col][c]
    return [aug[i][n] for i in range(n)]


def _median(values: Iterable[float], default: float = 0.0) -> float:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    return statistics.median(vals) if vals else default


# ---------------------------------------------------------------------------
# Per-series state
# ---------------------------------------------------------------------------


@dataclass
class SeriesState:
    """All learned state for one (station, fuel) demand series."""

    station_id: str
    fuel_type: str
    obs: dict[int, float] = field(default_factory=dict)          # tick -> demand
    profile: dict[int, list[float]] = field(default_factory=dict)  # tod -> [demand]
    one_step_errors: deque[float] = field(default_factory=lambda: deque(maxlen=_ONE_STEP_ERROR_CAP))
    ewma_ratio: float = 1.0
    ewma_ready: bool = False
    last_update_tick: int | None = None

    def add_observation(self, tick: int, demand: float, season_length: int) -> None:
        self.obs[tick] = demand
        tod = tick % season_length
        bucket = self.profile.setdefault(tod, [])
        bucket.append(demand)
        if len(bucket) > _PROFILE_BUCKET_CAP:
            del bucket[: len(bucket) - _PROFILE_BUCKET_CAP]

    def prune(self, now_tick: int, season_length: int) -> None:
        cutoff = now_tick - season_length * _OBS_KEEP_TICKS_FACTOR
        for tick in [t for t in self.obs if t < cutoff]:
            del self.obs[tick]

    def sorted_ticks(self) -> list[int]:
        return sorted(self.obs)

    def series_median(self, fallback: float) -> float:
        if not self.obs:
            return fallback
        return _median(self.obs.values(), fallback)


# ---------------------------------------------------------------------------
# Pooled online ridge model (one per fuel type)
# ---------------------------------------------------------------------------

_FEATURE_COUNT = 12


def _feature_row(
    *,
    target_tick: int,
    season_length: int,
    scale: float,
    region_f: float,
    demand_multiplier: float,
    lag1: float,
    lag_season: float,
    ewma_ratio: float,
    roll6: float,
) -> list[float]:
    tod = (target_tick % season_length) / season_length
    angle = 2.0 * math.pi * tod
    return [
        1.0,
        scale,
        region_f,
        demand_multiplier,
        math.sin(angle),
        math.cos(angle),
        math.sin(2.0 * angle),
        math.cos(2.0 * angle),
        lag1,
        lag_season,
        ewma_ratio,
        roll6,
    ]


@dataclass
class RidgeState:
    """Accumulated second/third moments for the closed-form ridge solution."""

    A: list[list[float]] = field(
        default_factory=lambda: [[0.0] * _FEATURE_COUNT for _ in range(_FEATURE_COUNT)]
    )
    b: list[float] = field(default_factory=lambda: [0.0] * _FEATURE_COUNT)
    weights: list[float] | None = None
    samples: int = 0
    last_trained_tick: int | None = None
    last_trained_at_epoch: float | None = None
    # Prequential evaluation against the untrained ensemble (promotion gate).
    eval_trained: deque[tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=120)
    )

    def accumulate(self, x: list[float], y: float, decay: float) -> None:
        if self.samples:
            for i in range(_FEATURE_COUNT):
                row = self.A[i]
                bi = self.b[i] * decay
                for j in range(_FEATURE_COUNT):
                    row[j] *= decay
                self.b[i] = bi
        for i, xi in enumerate(x):
            row = self.A[i]
            for j, xj in enumerate(x):
                row[j] += xi * xj
            self.b[i] += xi * y
        self.samples += 1

    def solve(self, lambda_reg: float) -> bool:
        n = _FEATURE_COUNT
        reg = [[self.A[i][j] + (lambda_reg if i == j else 0.0) for j in range(n)] for i in range(n)]
        solution = _solve_linear(reg, self.b[:])
        if solution is None:
            self.weights = None
            return False
        if any(not math.isfinite(w) for w in solution):
            self.weights = None
            return False
        self.weights = solution
        return True

    def predict(self, x: list[float]) -> float | None:
        if self.weights is None:
            return None
        return sum(w * xi for w, xi in zip(self.weights, x))

    def recent_mae(self) -> tuple[float, float] | None:
        """(trained MAE, baseline MAE) over the stored prequential pairs."""
        if len(self.eval_trained) < 30:
            return None
        trained = statistics.fmean(abs(e_t) for e_t, _ in self.eval_trained)
        baseline = statistics.fmean(abs(e_b) for _, e_b in self.eval_trained)
        return trained, baseline


# ---------------------------------------------------------------------------
# Prequential residual store (multi-horizon uncertainty)
# ---------------------------------------------------------------------------


@dataclass
class PendingForecasts:
    """Forecasts issued at some tick for future target ticks."""

    # (station, fuel, target_tick) -> {horizon_k: forecast_value}
    entries: dict[tuple[str, str, int], dict[int, float]] = field(default_factory=dict)

    def remember(self, key: SeriesKey, now_tick: int, point: list[float]) -> None:
        for offset, value in enumerate(point, start=1):
            self.entries[(key[0], key[1], now_tick + offset)] = {offset: value}
        self.prune(now_tick)

    def take(self, key: SeriesKey, target_tick: int) -> dict[int, float]:
        entry = self.entries.pop((key[0], key[1], target_tick), {})
        return entry

    def prune(self, now_tick: int) -> None:
        stale = [k for k in self.entries if k[2] < now_tick - _PENDING_MAX_AGE_TICKS]
        for k in stale:
            del self.entries[k]


# ---------------------------------------------------------------------------
# The demand model
# ---------------------------------------------------------------------------


@dataclass
class ForecastOutput:
    point: list[float]
    p10: list[float]
    p90: list[float]
    method: str
    confidence: str
    history_count: int
    ewma_level: float | None
    seasonal_reference: float | None
    trained_used: bool
    trained_samples: int
    reasons: list[dict[str, Any]]


class DemandModel:
    """Trained demand-forecasting model for all (station, fuel) series."""

    def __init__(self, policy: PolicyConfig, world: "WorldContext") -> None:
        self.policy = policy
        self.world = world  # station profiles / regions / ticks-per-day context
        self.season_length = policy.season_length_ticks
        self.series: dict[SeriesKey, SeriesState] = {}
        self.ridge: dict[str, RidgeState] = {}
        self.pending = PendingForecasts()
        self.last_fit_tick: int | None = None

    # -- context helpers ----------------------------------------------------

    def _world(self, key: SeriesKey) -> tuple[float, float, float]:
        """(profile prior per tick, region factor, station scale fallback)."""
        info = self.world.series_context(key[0])
        fuel = key[1]
        per_tick = priors.prior_per_tick(info.profile, fuel, self.season_length)
        rf = priors.region_factor(info.region_id)
        return per_tick * rf * info.demand_multiplier_base, rf, info.demand_multiplier_base

    def _profile_estimate(self, state: SeriesState, tick: int) -> tuple[float, float]:
        """(shrunk seasonal estimate for this tick, unshrunk median)."""
        prior, _, _ = self._world((state.station_id, state.fuel_type))
        bucket = state.profile.get(tick % self.season_length, [])
        raw = _median(bucket, prior)
        # Shrink toward the documented prior until the bucket has history.
        weight = min(len(bucket), 16)
        shrunk = (raw * weight + prior * 8.0) / (weight + 8.0)
        return max(0.0, shrunk), max(0.0, raw)

    def state(self, key: SeriesKey) -> SeriesState:
        s = self.series.get(key)
        if s is None:
            s = SeriesState(station_id=key[0], fuel_type=key[1])
            self.series[key] = s
        return s

    def ridge_state(self, fuel: str) -> RidgeState:
        r = self.ridge.get(fuel)
        if r is None:
            r = RidgeState()
            self.ridge[fuel] = r
        return r

    def series_context(self, station_id: str) -> Any:
        return self.world.series_context(station_id)

    def observations(self, key: SeriesKey, limit: int = 400) -> list[tuple[int, float]]:
        s = self.series.get(key)
        if not s:
            return []
        return sorted(s.obs.items())[-limit:]

    # -- training -----------------------------------------------------------

    def fit_full(self, history: dict[SeriesKey, list[tuple[int, float]]], now_tick: int) -> int:
        """Batch-fit all series (bootstrap from /demand-history)."""
        count = 0
        for key, rows in history.items():
            state = self.state(key)
            for tick, demand in rows:
                state.add_observation(tick, demand, self.season_length)
                count += 1
            state.prune(now_tick, self.season_length)
        self._train_ridge(now_tick)
        self._init_ewma_states()
        self.last_fit_tick = now_tick
        return count

    def _init_ewma_states(self) -> None:
        for key, state in self.series.items():
            if state.ewma_ready or not state.obs:
                continue
            ratios = []
            for tick, demand in sorted(state.obs.items())[-2 * self.season_length :]:
                est, _ = self._profile_estimate(state, tick)
                if est > 1e-9:
                    ratios.append(demand / est)
            if ratios:
                state.ewma_ratio = min(4.0, max(0.25, _median(ratios, 1.0)))
                state.ewma_ready = True

    def _lag_values(self, state: SeriesState, target_tick: int) -> tuple[float, float, float, float]:
        """(lag1, lag_season, ewma_ratio, roll6_ratio) as of just before target_tick."""
        scale = state.series_median(self._world((state.station_id, state.fuel_type))[2])
        lag1 = state.obs.get(target_tick - 1, scale)
        lag_season = state.obs.get(target_tick - self.season_length, scale)
        ratios: list[float] = []
        for back in range(1, 7):
            t = target_tick - back
            d = state.obs.get(t)
            if d is None:
                continue
            est, _ = self._profile_estimate(state, t)
            if est > 1e-9:
                ratios.append(d / est)
        roll6 = _median(ratios, state.ewma_ratio if state.ewma_ready else 1.0)
        return lag1, lag_season, (state.ewma_ratio if state.ewma_ready else 1.0), roll6

    def _train_ridge(self, now_tick: int) -> None:
        """(Re)build pooled ridge weights per fuel from stored observations."""
        for fuel in self.policy.fuel_types:
            ridge = self.ridge_state(fuel)
            pairs: list[tuple[list[float], float]] = []
            for key, state in self.series.items():
                if key[1] != fuel or not state.obs:
                    continue
                info = self.world.series_context(key[0])
                scale = state.series_median(self._world(key)[2])
                ticks = state.sorted_ticks()
                for t in ticks:
                    demand = state.obs.get(t)
                    if demand is None:
                        continue
                    lag1, lag_season, ewma_r, roll6 = self._lag_values(state, t)
                    x = _feature_row(
                        target_tick=t,
                        season_length=self.season_length,
                        scale=scale,
                        region_f=priors.region_factor(info.region_id),
                        demand_multiplier=info.demand_multiplier_base,
                        lag1=lag1,
                        lag_season=lag_season,
                        ewma_ratio=ewma_r,
                        roll6=roll6,
                    )
                    pairs.append((x, demand))
            if not pairs:
                continue
            # Rebuild from scratch (deterministic) rather than growing unbounded.
            fresh = RidgeState(last_trained_tick=ridge.last_trained_tick)
            decay = 0.998
            for idx, (x, y) in enumerate(pairs):
                # Apply decay by tick distance to the newest observation.
                fresh.accumulate(x, y, 1.0 if idx == 0 else decay)
            if fresh.solve(lambda_reg=1e-3 * max(1, fresh.samples)):
                fresh.samples = ridge.samples + len(pairs)
                fresh.last_trained_tick = now_tick
                fresh.last_trained_at_epoch = time.time()
                fresh.eval_trained = ridge.eval_trained
                self.ridge[fuel] = fresh

    def maybe_retrain(self, now_tick: int) -> bool:
        if self.last_fit_tick is None:
            self.last_fit_tick = now_tick
            return False
        if now_tick - self.last_fit_tick >= self.policy.training_interval_ticks:
            self._train_ridge(now_tick)
            self.last_fit_tick = now_tick
            return True
        return False

    # -- online updates -------------------------------------------------------

    def update(
        self,
        key: SeriesKey,
        tick: int,
        demand: float,
        season_length: int,
    ) -> None:
        """Ingest one completed observation, updating prequential errors,
        the EWMA level and the online ridge moments.

        Must be called AFTER forecasts for ``tick`` were issued (prequential
        evaluation), never on the same tick twice (duplicates are ignored).
        """
        state = self.state(key)
        if tick in state.obs:  # duplicate poll / replayed row
            return
        if not math.isfinite(demand) or demand < 0:
            return

        # 1) Prequential one-step error against the seasonal path BEFORE learning.
        est, _ = self._profile_estimate(state, tick)
        base = est * (state.ewma_ratio if state.ewma_ready else 1.0)
        state.one_step_errors.append(demand - base)

        # 2) Ridge: record the trained-vs-baseline comparison, then learn.
        info = self.world.series_context(key[0])
        scale = state.series_median(self._world(key)[2])
        lag1, lag_season, ewma_r, roll6 = self._lag_values(state, tick)
        x = _feature_row(
            target_tick=tick,
            season_length=season_length,
            scale=scale,
            region_f=priors.region_factor(info.region_id),
            demand_multiplier=info.demand_multiplier_base,
            lag1=lag1,
            lag_season=lag_season,
            ewma_ratio=ewma_r,
            roll6=roll6,
        )
        ridge = self.ridge_state(key[1])
        trained_pred = ridge.predict(x)
        if trained_pred is not None and base > 1e-9:
            trained_pred = max(0.0, trained_pred)
            ridge.eval_trained.append((demand - trained_pred, demand - base))

        decay = 0.998 ** max(0, min(50, tick - (state.last_update_tick or tick)))
        ridge.accumulate(x, demand, decay)
        if ridge.samples and ridge.samples % 24 == 0:
            ridge.solve(lambda_reg=1e-3 * max(1, ridge.samples))

        # 3) Store observation and update EWMA level ratio.
        state.add_observation(tick, demand, season_length)
        if est > 1e-9:
            ratio = min(4.0, max(0.25, demand / est))
            if not state.ewma_ready:
                state.ewma_ratio = ratio
                state.ewma_ready = True
            else:
                state.ewma_ratio = 0.85 * state.ewma_ratio + 0.15 * ratio
        state.last_update_tick = tick
        state.prune(tick, season_length)

    def observe_without_prediction(self, key: SeriesKey, tick: int, demand: float, season_length: int) -> None:
        """Backfill history rows missed by the live loop (no prequential bookkeeping)."""
        state = self.state(key)
        if tick in state.obs or not math.isfinite(demand) or demand < 0:
            return
        state.add_observation(tick, demand, season_length)
        state.prune(tick, season_length)

    # -- prediction -----------------------------------------------------------

    def _trained_promoted(self, fuel: str) -> tuple[bool, str]:
        ridge = self.ridge.get(fuel)
        if ridge is None or ridge.weights is None:
            return False, "no trained weights"
        if ridge.samples < self.policy.training_min_samples:
            return (
                False,
                f"samples {ridge.samples} < required {self.policy.training_min_samples}",
            )
        mae = ridge.recent_mae()
        if mae is None:
            return False, "insufficient prequential evaluation"
        trained_mae, baseline_mae = mae
        if trained_mae > baseline_mae * 1.02:
            return (
                False,
                f"trained MAE {trained_mae:.1f}L worse than baseline {baseline_mae:.1f}L",
            )
        return True, f"trained MAE {trained_mae:.1f}L vs baseline {baseline_mae:.1f}L"

    def _error_quantiles(self, key: SeriesKey, horizon: int) -> tuple[float, float] | None:
        """Empirical (p10, p90) of prequential residuals for this horizon."""
        state = self.series.get(key)
        if state is None:
            return None
        pool: list[float] = []
        by_k = getattr(state, "err_by_k", None)
        if by_k:
            exact = by_k.get(horizon, [])
            if len(exact) >= _QUANTILE_MIN_SAMPLES:
                s = sorted(exact)
                return _quantile(s, 0.10), _quantile(s, 0.90)
            for blo, bhi in _ERROR_BUCKETS:
                if blo <= horizon <= bhi:
                    pool = [v for kk in range(blo, bhi + 1) for v in by_k.get(kk, [])]
                    break
            if len(pool) >= _QUANTILE_MIN_SAMPLES:
                s = sorted(pool)
                return _quantile(s, 0.10), _quantile(s, 0.90)
        # Fallback: one-step residual spread widened with horizon.
        errs = list(state.one_step_errors)
        if len(errs) >= _QUANTILE_MIN_SAMPLES:
            s = sorted(errs)
            spread = 1.0 + 0.15 * math.sqrt(max(1, horizon))
            return _quantile(s, 0.10) * spread, _quantile(s, 0.90) * spread
        return None

    def record_pending_errors(self, key: SeriesKey, target_tick: int, actual: float) -> None:
        """Compare stored forecasts for target_tick with the actual value."""
        issued = self.pending.take(key, target_tick)
        if not issued:
            return
        state = self.state(key)
        if not hasattr(state, "err_by_k"):
            state.err_by_k = {}  # type: ignore[attr-defined]
        by_k: dict[int, list[float]] = state.err_by_k  # type: ignore[attr-defined]
        for k, value in issued.items():
            bucket = by_k.setdefault(k, [])
            bucket.append(actual - value)
            if len(bucket) > _ONE_STEP_ERROR_CAP:
                del bucket[: len(bucket) - _ONE_STEP_ERROR_CAP]

    def predict(
        self,
        key: SeriesKey,
        now_tick: int,
        horizon: int,
        live_multiplier: float,
        season_length: int | None = None,
    ) -> ForecastOutput:
        """Forecast demand for ticks now_tick+1 .. now_tick+horizon."""
        sl = season_length or self.season_length
        state = self.state(key)
        prior, region_f, base_multiplier = self._world(key)
        n_obs = len(state.obs)

        # Seasonal path scaled by the EWMA level ratio.
        profile_ref = self._profile_estimate(state, now_tick + 1)[0]
        level = state.ewma_ratio if state.ewma_ready else 1.0
        base: list[float] = []
        for k in range(1, horizon + 1):
            est, _ = self._profile_estimate(state, now_tick + k)
            base.append(max(0.0, est * level))

        reasons: list[dict[str, Any]] = []
        trained_used = False
        trained_samples = 0
        method = "seasonal_naive_ewma"
        confidence = "low"

        if n_obs < self.policy.anomaly_min_history:
            # Cold start: documented profile prior for this tick-of-day.
            info = self.world.series_context(key[0])
            for k in range(1, horizon + 1):
                hour = int(((now_tick + k) * self.world.tick_minutes / 60.0) % 24)
                per_tick = priors.prior_per_tick(info.profile, key[1], sl)
                shaped = (
                    per_tick
                    * priors.region_factor(info.region_id)
                    * info.demand_multiplier_base
                    * priors.hour_factor(info.profile, hour)
                    * live_multiplier
                )
                base[k - 1] = max(0.0, shaped)
            method = "cold_start_prior"
            reasons.append(
                {
                    "code": "COLD_START",
                    "detail": "Using documented profile prior; insufficient observations for a trained estimate.",
                    "values": {"observations": n_obs},
                }
            )
        else:
            confidence = "medium" if n_obs >= self.season_length else "low"
            reasons.append(
                {
                    "code": "SEASONAL_LEVEL",
                    "detail": "Seasonal tick-of-day profile scaled by the recent demand level (EWMA).",
                    "values": {
                        "observations": n_obs,
                        "level_ratio": round(level, 3),
                        "profile_reference_liters": round(profile_ref, 1),
                    },
                }
            )
            promoted, promo_reason = self._trained_promoted(key[1])
            ridge = self.ridge.get(key[1])
            trained_samples = ridge.samples if ridge else 0
            if promoted and ridge is not None and ridge.weights is not None:
                scale = state.series_median(self._world(key)[2])
                lag1, lag_season, ewma_r, roll6 = self._lag_values(state, now_tick + 1)
                x = _feature_row(
                    target_tick=now_tick + 1,
                    season_length=sl,
                    scale=scale,
                    region_f=region_f,
                    demand_multiplier=base_multiplier * live_multiplier,
                    lag1=lag1,
                    lag_season=lag_season,
                    ewma_ratio=ewma_r,
                    roll6=roll6,
                )
                trained_pred = ridge.predict(x)
                if trained_pred is not None and math.isfinite(trained_pred) and base[0] > 1e-9:
                    trained_pred = max(0.0, trained_pred)
                    w = self.policy.trained_model_weight
                    blended1 = (1.0 - w) * base[0] + w * trained_pred
                    correction = blended1 / base[0]
                    for k in range(1, horizon + 1):
                        factor = 1.0 + (correction - 1.0) * math.exp(-(k - 1) / 8.0)
                        base[k - 1] = max(0.0, base[k - 1] * factor)
                    trained_used = True
                    method = "trained_ensemble"
                    confidence = "high" if n_obs >= 2 * self.season_length else "medium"
                    reasons.append(
                        {
                            "code": "TRAINED_MODEL_ADJUSTMENT",
                            "detail": (
                                "Trained per-fuel model adjusts the seasonal level; "
                                "adjustment decays over the horizon."
                            ),
                            "values": {
                                "trained_next_tick_liters": round(trained_pred, 1),
                                "ensemble_next_tick_liters": round(base[0], 1),
                                "weight": w,
                                "samples": ridge.samples,
                            },
                        }
                    )
                else:
                    reasons.append(
                        {
                            "code": "TRAINED_MODEL_UNAVAILABLE",
                            "detail": "Trained model prediction not usable; using seasonal ensemble.",
                            "values": {},
                        }
                    )
            else:
                reasons.append(
                    {
                        "code": "TRAINED_MODEL_NOT_PROMOTED",
                        "detail": promo_reason,
                        "values": {"samples": trained_samples},
                    }
                )

        # Live demand multiplier (events) adjusts open-station demand.
        if abs(live_multiplier - 1.0) > 1e-9 and method != "cold_start_prior":
            for k in range(1, horizon + 1):
                base[k - 1] = max(0.0, base[k - 1] * live_multiplier)
            reasons.append(
                {
                    "code": "LIVE_MULTIPLIER",
                    "detail": "Live station demand multiplier (active events) applied.",
                    "values": {"multiplier": round(live_multiplier, 3)},
                }
            )

        # Uncertainty from stored prequential residuals.
        p10: list[float] = []
        p90: list[float] = []
        for k in range(1, horizon + 1):
            q = self._error_quantiles(key, k)
            if q is None:
                spread = 0.4 + 0.1 * math.sqrt(k)
                p10.append(max(0.0, base[k - 1] * (1.0 - spread)))
                p90.append(base[k - 1] * (1.0 + spread))
            else:
                lo, hi = q
                p10.append(max(0.0, base[k - 1] + lo))
                p90.append(max(0.0, base[k - 1] + hi))

        return ForecastOutput(
            point=[round(v, 2) for v in base],
            p10=[round(v, 2) for v in p10],
            p90=[round(v, 2) for v in p90],
            method=method,
            confidence=confidence,
            history_count=n_obs,
            ewma_level=round(level, 4) if state.ewma_ready else None,
            seasonal_reference=round(profile_ref, 2),
            trained_used=trained_used,
            trained_samples=trained_samples,
            reasons=reasons,
        )

    # -- persistence ----------------------------------------------------------

    def to_json(self) -> str:
        payload = {
            "version": 1,
            "season_length": self.season_length,
            "last_fit_tick": self.last_fit_tick,
            "series": [
                {
                    "station_id": s.station_id,
                    "fuel_type": s.fuel_type,
                    "obs": {str(t): d for t, d in s.obs.items()},
                    "profile": {str(tod): v for tod, v in s.profile.items()},
                    "one_step_errors": list(s.one_step_errors),
                    "ewma_ratio": s.ewma_ratio,
                    "ewma_ready": s.ewma_ready,
                    "last_update_tick": s.last_update_tick,
                    "err_by_k": {
                        str(k): list(v) for k, v in getattr(s, "err_by_k", {}).items()
                    },
                }
                for s in self.series.values()
            ],
            "ridge": {
                fuel: {
                    "A": r.A,
                    "b": r.b,
                    "weights": r.weights,
                    "samples": r.samples,
                    "last_trained_tick": r.last_trained_tick,
                    "last_trained_at_epoch": r.last_trained_at_epoch,
                    "eval_trained": list(r.eval_trained),
                }
                for fuel, r in self.ridge.items()
            },
            "pending": {
                f"{k[0]}|{k[1]}|{k[2]}": v for k, v in self.pending.entries.items()
            },
        }
        return json.dumps(payload, separators=(",", ":"))

    def load_json(self, raw: str) -> bool:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return False
        if payload.get("version") != 1:
            return False
        try:
            self.season_length = int(payload.get("season_length", self.season_length))
            self.last_fit_tick = payload.get("last_fit_tick")
            self.series = {}
            for row in payload.get("series", []):
                s = SeriesState(
                    station_id=row["station_id"],
                    fuel_type=row["fuel_type"],
                    obs={int(t): float(d) for t, d in row.get("obs", {}).items()},
                    profile={
                        int(tod): [float(v) for v in vals]
                        for tod, vals in row.get("profile", {}).items()
                    },
                    ewma_ratio=float(row.get("ewma_ratio", 1.0)),
                    ewma_ready=bool(row.get("ewma_ready", False)),
                    last_update_tick=row.get("last_update_tick"),
                )
                for e in row.get("one_step_errors", []):
                    s.one_step_errors.append(float(e))
                err_by_k: dict[int, list[float]] = {}
                for k, vals in row.get("err_by_k", {}).items():
                    err_by_k[int(k)] = [float(v) for v in vals]
                s.err_by_k = err_by_k  # type: ignore[attr-defined]
                self.series[(s.station_id, s.fuel_type)] = s
            self.ridge = {}
            for fuel, r in payload.get("ridge", {}).items():
                state = RidgeState(
                    A=[[float(v) for v in row] for row in r.get("A", [])],
                    b=[float(v) for v in r.get("b", [])],
                    weights=(
                        [float(v) for v in r["weights"]] if r.get("weights") else None
                    ),
                    samples=int(r.get("samples", 0)),
                    last_trained_tick=r.get("last_trained_tick"),
                    last_trained_at_epoch=r.get("last_trained_at_epoch"),
                )
                for pair in r.get("eval_trained", []):
                    state.eval_trained.append((float(pair[0]), float(pair[1])))
                self.ridge[fuel] = state
            self.pending = PendingForecasts()
            for compound, issued in payload.get("pending", {}).items():
                try:
                    station, fuel, tick = compound.split("|")
                    self.pending.entries[(station, fuel, int(tick))] = {
                        int(k): float(v) for k, v in issued.items()
                    }
                except (ValueError, TypeError):
                    continue
            return True
        except (KeyError, TypeError, ValueError):
            return False
