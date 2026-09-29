"""Typed contracts for everything the intelligence engine produces.

These models are the stable API surface between the engine internals, the
FastAPI routes, and the frontend. Every numeric claim carries provenance so
the UI can show *why* a number exists (spec: reasons + confidence + flags).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.simulator.models import FuelType


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Enumerations used across predictions, alerts, and plans
# ---------------------------------------------------------------------------


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INVALID = "invalid"


class RiskTier(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    WATCH = "watch"
    NORMAL = "normal"
    UNKNOWN = "unknown"


class ForecastMethod(str, Enum):
    COLD_START = "cold_start_prior"          # documented profile prior only
    SEASONAL_NAIVE = "seasonal_naive_ewma"   # ensemble of profile + recent level
    TRAINED_ENSEMBLE = "trained_ensemble"    # blend with trained online model


class AnomalyKind(str, Enum):
    NONE = "none"
    SPIKE = "demand_spike_observed"
    DROP = "demand_drop_observed"


class FindingType(str, Enum):
    # observed anomalies / state findings
    DEMAND_SPIKE = "DEMAND_SPIKE"
    DEMAND_DROP = "DEMAND_DROP"
    DEMAND_LEVEL_SHIFT = "DEMAND_LEVEL_SHIFT"
    CURRENT_STOCKOUT = "CURRENT_STOCKOUT"
    STATION_OUTAGE = "STATION_OUTAGE"
    DEPOT_CONSTRAINT = "DEPOT_CONSTRAINT"
    ROUTE_BLOCKED = "ROUTE_BLOCKED"
    ROUTE_DELAY = "ROUTE_DELAY"
    SUPPLY_ETA_SLIPPAGE = "SUPPLY_ETA_SLIPPAGE"
    SUPPLY_OVERDUE = "SUPPLY_OVERDUE"
    SUPPLY_SHORTFALL = "SUPPLY_SHORTFALL"
    DATA_STALE = "DATA_STALE"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"
    # predictive findings
    PROJECTED_STOCKOUT = "PROJECTED_STOCKOUT"
    REPLENISHMENT_TOO_LATE = "REPLENISHMENT_TOO_LATE"
    NO_TIMELY_REPLENISHMENT = "NO_TIMELY_REPLENISHMENT"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertState(str, Enum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    RUN_ENDED = "run_ended"


class PlanStatus(str, Enum):
    DRAFT = "draft"                        # computed, visible, not yet reviewed
    APPROVED = "approved"                  # operator approved, ready to submit
    SUBMITTING = "submitting"
    PARTIALLY_APPLIED = "partially_applied"
    APPLIED = "applied"
    REJECTED = "rejected"                  # simulator rejected an action
    FAILED = "failed"                      # execution could not complete
    EXPIRED = "expired"


class ActionStatus(str, Enum):
    PENDING_SUBMISSION = "pending_submission"
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    UNKNOWN_OUTCOME = "unknown_outcome"
    CANCELLED = "cancelled"


class RejectionReason(str, Enum):
    NONE = "none"
    EXECUTION_DISABLED = "execution_disabled"
    SNAPSHOT_STALE = "snapshot_stale"
    PLAN_EXPIRED = "plan_expired"
    PLAN_MISSING = "plan_missing"
    ALREADY_EXECUTED = "already_executed"
    SIMULATOR_UNAVAILABLE = "simulator_unavailable"
    REJECTED_BY_SIMULATOR = "rejected_by_simulator"
    AMBIGUOUS_OUTCOME = "ambiguous_outcome"


# ---------------------------------------------------------------------------
# Forecast structures
# ---------------------------------------------------------------------------


class Reason(StrictModel):
    code: str
    detail: str
    values: dict[str, Any] = Field(default_factory=dict)


class ForecastPoint(StrictModel):
    """Per-station/fuel demand model with per-tick point forecasts."""

    station_id: str
    fuel_type: FuelType
    method: ForecastMethod
    confidence: Confidence
    # Point forecast for each future tick offset (1-based relative to snapshot).
    point: list[float]
    # Empirical p10/p90 of past one-step errors applied to the point path.
    p10: list[float]
    p90: list[float]
    history_count: int
    tick_of_day: int | None = None
    ewma_level: float | None = None
    seasonal_reference: float | None = None
    trained_model_used: bool = False
    trained_model_samples: int = 0
    reasons: list[Reason] = Field(default_factory=list)


class InboundDelivery(StrictModel):
    """A confirmed unit destined to a station (existing allocation) — never a
    proposal, and never a depot supply arrival (those land at depots)."""

    allocation_id: int
    source_depot_id: str
    route_id: str
    fuel_type: FuelType
    quantity_liters: float
    expected_arrival_tick: int
    status: str


class StationFuelProjection(StrictModel):
    """Deterministic, shared inventory projection for one station/fuel cell."""

    station_id: str
    fuel_type: FuelType
    current_inventory_liters: float
    capacity_liters: float
    inbound: list[InboundDelivery]
    projected_inventory: list[float]      # end-of-tick inventory for t+1..t+H
    projected_demand: list[float]
    projected_unmet: list[float]
    expected_unmet_liters: float
    first_unmet_offset: int | None        # ticks from now until first unmet demand
    first_zero_offset: int | None         # ticks until tank hits zero
    burn_rate_liters_per_tick: float | None  # display-only quick estimate
    daily_profile_reference_liters: float | None = None


class PredictionResult(StrictModel):
    snapshot_id: str
    as_of_tick: int
    horizon_ticks: int
    forecasts: list[ForecastPoint]
    projections: list[StationFuelProjection]
    risk_by_cell: dict[str, RiskTier]
    risk_by_station: dict[str, RiskTier]
    probability_status: Literal[
        "EMPIRICAL_UNCALIBRATED", "UNAVAILABLE"
    ] = "EMPIRICAL_UNCALIBRATED"
    generated_at_epoch: float
    generated_at_sim_time: str | None = None
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Detection structures
# ---------------------------------------------------------------------------


class Evidence(StrictModel):
    name: str
    value: Any
    unit: str | None = None
    baseline: Any = None
    threshold: Any = None


class Finding(StrictModel):
    finding_id: str
    type: FindingType
    category: Literal["OBSERVED", "PREDICTED", "ENGINEERING"]
    entity_ids: list[str]
    fuel_type: FuelType | None = None
    severity: Severity
    confidence: Confidence
    title: str
    detail: str
    evidence: list[Evidence] = Field(default_factory=list)
    recommendation_hints: list[str] = Field(default_factory=list)
    first_seen_tick: int
    last_seen_tick: int
    observed_at_epoch: float


class DetectionResult(StrictModel):
    snapshot_id: str
    as_of_tick: int
    findings: list[Finding]
    blocked_station_fuel: list[str] = Field(default_factory=list)  # "station:fuel"
    generated_at_epoch: float


# ---------------------------------------------------------------------------
# Recommendation / plan structures
# ---------------------------------------------------------------------------


class ProposedAction(StrictModel):
    action_id: str                      # stable within a plan
    source_depot_id: str
    destination_station_id: str
    route_id: str
    fuel_type: FuelType
    quantity_liters: float
    dispatch_tick: int                  # tick when submitted (== snapshot tick)
    expected_arrival_tick: int
    transit_ticks: int
    idempotency_key: str


class ActionOutcome(StrictModel):
    action_id: str
    status: ActionStatus
    simulator_allocation_id: int | None = None
    http_status: int | None = None
    detail: str | None = None


class ImpactSummary(StrictModel):
    expected_unmet_before_liters: float
    expected_unmet_after_liters: float
    unmet_avoided_liters: float
    stockouts_before: int
    stockouts_after: int
    worst_service_ratio_before: float | None
    worst_service_ratio_after: float | None
    note: str


class DepotStateAfter(StrictModel):
    depot_id: str
    fuel_type: FuelType
    remaining_usable_liters: float
    dispatch_headroom_liters: float


class Recommendation(StrictModel):
    """Everything the operator needs to review one proposed shipment."""

    action: ProposedAction
    severity: Severity
    reason_codes: list[str]
    reasons: list[Reason]
    serving_findings: list[str]         # finding_ids that motivated this action
    constraints_checked: list[str]
    binding_constraint: str | None
    estimated_arrival_tick: int
    alternatives: list[dict[str, Any]] = Field(default_factory=list)


class NoActionReason(StrictModel):
    station_id: str
    fuel_type: FuelType
    reason_code: str
    detail: str


class DecisionPlan(StrictModel):
    """The complete, validated, internally consistent proposed plan."""

    plan_id: str
    run_id: str
    snapshot_id: str
    as_of_tick: int
    generated_at_epoch: float
    generated_at_sim_time: str | None = None
    status: PlanStatus = PlanStatus.DRAFT
    method: Literal["GREEDY_CONSTRAINED", "FALLBACK_UNIFORM", "NO_ACTION"] = (
        "GREEDY_CONSTRAINED"
    )
    policy_version: str = "policy-v1"
    recommendations: list[Recommendation] = Field(default_factory=list)
    no_action_reasons: list[NoActionReason] = Field(default_factory=list)
    impact: ImpactSummary | None = None
    depot_state_after: list[DepotStateAfter] = Field(default_factory=list)
    uncovered_needs: list[NoActionReason] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requires_operator_approval: bool = True
    approved_by: str | None = None
    approved_at_epoch: float | None = None
    executed_at_epoch: float | None = None
    outcomes: list[ActionOutcome] = Field(default_factory=list)
    rejection_reason: RejectionReason = RejectionReason.NONE


# ---------------------------------------------------------------------------
# Engine status / health (for the system status panel + observability)
# ---------------------------------------------------------------------------


class TrainingStatus(StrictModel):
    trained: bool
    samples: int
    last_trained_tick: int | None = None
    last_trained_at_epoch: float | None = None
    validation_mae_liters: float | None = None
    baseline_mae_liters: float | None = None
    improvement_vs_baseline: float | None = None
    message: str = ""


class EngineStatus(StrictModel):
    engine: Literal["healthy", "degraded", "disabled"] = "healthy"
    last_run_tick: int | None = None
    last_run_at_epoch: float | None = None
    last_error: str | None = None
    snapshot_age_seconds: float | None = None
    run_count: int = 0
    total_runtime_ms: float = 0.0
    training: TrainingStatus
    execution_enabled: bool = True
    fallback_active: bool = False
