"""Policy configuration for the intelligence engine.

Every numeric threshold here is an explicit, operator-tunable policy choice,
not a simulator fact. Values follow docs/recommendation-engine-design.md and
the Prediction/Detection/Decision Intelligence specifications.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class PolicyConfig:
    """Operator-facing policy knobs. All times are simulator ticks unless named
    ``*_seconds`` (wall-clock). All volumes are liters (the simulator unit)."""

    # --- Planning horizons (ticks) ------------------------------------------
    planning_horizon: int = _env_int("INTELLIGENCE_HORIZON_TICKS", 24)
    immediate_risk_horizon: int = _env_int("INTELLIGENCE_IMMEDIATE_HORIZON_TICKS", 6)

    # --- Forecasting ---------------------------------------------------------
    # Tick-of-day seasonality: the default world has 96 ticks/day (15 min ticks).
    season_length_ticks: int = _env_int("INTELLIGENCE_SEASON_TICKS", 96)
    # Blend weight of the trained model vs the seasonal-naive/EWMA ensemble.
    trained_model_weight: float = _env_float("INTELLIGENCE_TRAINED_WEIGHT", 0.6)
    # Required completed observations before a trained model is promoted.
    training_min_samples: int = _env_int("INTELLIGENCE_TRAINING_MIN_SAMPLES", 200)
    # Multiplied by season_length to decide when retraining is worthwhile.
    training_interval_ticks: int = _env_int("INTELLIGENCE_TRAIN_INTERVAL_TICKS", 96)

    # --- Risk tiers ----------------------------------------------------------
    watch_p_stockout: float = _env_float("INTELLIGENCE_WATCH_P", 0.30)
    high_p_stockout: float = _env_float("INTELLIGENCE_HIGH_P", 0.70)

    # --- Allocator -----------------------------------------------------------
    # Cover forecast demand for this many ticks after a delivery lands.
    desired_cover_ticks: int = _env_int("INTELLIGENCE_DESIRED_COVER_TICKS", 6)
    # Extra stock held as a soft safety buffer (fraction of cover demand).
    safety_buffer_fraction: float = _env_float("INTELLIGENCE_SAFETY_BUFFER", 0.15)
    # Depot hard reserve fraction (hard constraint C11).
    depot_reserve_fraction: float = _env_float("INTELLIGENCE_DEPOT_RESERVE", 0.10)
    # Share of one route's max_shipment used as one greedy batch.
    batch_fraction_of_route: float = _env_float("INTELLIGENCE_BATCH_FRACTION", 0.5)
    # Upper bound on greedy iterations (latency guard).
    max_plan_steps: int = _env_int("INTELLIGENCE_MAX_PLAN_STEPS", 64)
    # Wall-clock budget for one full planning computation (seconds).
    solver_wall_timeout_seconds: float = _env_float("INTELLIGENCE_SOLVER_TIMEOUT", 2.0)

    # --- Snapshot / freshness ------------------------------------------------
    snapshot_max_age_seconds: float = _env_float("INTELLIGENCE_SNAPSHOT_MAX_AGE", 30.0)
    stale_after_seconds: float = _env_float("INTELLIGENCE_STALE_AFTER", 60.0)

    # --- Background loop -----------------------------------------------------
    loop_interval_seconds: float = _env_float("INTELLIGENCE_LOOP_SECONDS", 5.0)
    loop_enabled: bool = _env_bool("INTELLIGENCE_LOOP_ENABLED", True)
    # Re-run prediction/detection only when the simulator tick advanced.
    loop_min_tick_delta: int = _env_int("INTELLIGENCE_LOOP_MIN_TICK_DELTA", 1)

    # --- History / training persistence --------------------------------------
    history_dir: str = os.getenv("INTELLIGENCE_HISTORY_DIR", "var/intelligence")
    # Fetch this many demand rows per station when bootstrapping history.
    bootstrap_demand_limit: int = _env_int("INTELLIGENCE_BOOTSTRAP_LIMIT", 2000)

    # --- Execution (operator-approved simulator writes) -----------------------
    # Master switch: POST /v1/allocations stays disabled unless enabled here.
    execution_enabled: bool = _env_bool("INTELLIGENCE_EXECUTION_ENABLED", True)
    # Revalidate the simulator state before submission; abort if older than this.
    revalidation_max_age_seconds: float = _env_float("INTELLIGENCE_REVALIDATE_MAX_AGE", 20.0)
    submission_timeout_seconds: float = _env_float("INTELLIGENCE_SUBMIT_TIMEOUT", 8.0)
    # Plan expiry: first of tick age or wall age.
    plan_expiry_ticks: int = _env_int("INTELLIGENCE_PLAN_EXPIRY_TICKS", 2)
    plan_expiry_seconds: float = _env_float("INTELLIGENCE_PLAN_EXPIRY_SECONDS", 120.0)

    # --- Detection ------------------------------------------------------------
    # Demand anomaly: robust-z entry threshold and materiality ratio.
    anomaly_z_enter: float = _env_float("INTELLIGENCE_ANOMALY_Z", 3.5)
    anomaly_materiality: float = _env_float("INTELLIGENCE_ANOMALY_MATERIALITY", 0.35)
    anomaly_min_history: int = _env_int("INTELLIGENCE_ANOMALY_MIN_HISTORY", 12)
    # Historical deviation from the same tick-of-day seasonal profile that
    # counts as a level shift (robust z of the EWMA residual distribution).
    level_shift_z: float = _env_float("INTELLIGENCE_LEVEL_SHIFT_Z", 4.0)
    # Route margin slowdown (actual/expected transit) treated as a delay.
    eta_slack_ratio: float = _env_float("INTELLIGENCE_ETA_SLACK", 1.5)

    fuel_types: tuple[str, ...] = field(default_factory=lambda: ("DIESEL", "PETROL", "OCTANE"))


POLICY = PolicyConfig()
