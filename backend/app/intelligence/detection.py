"""Detection: observed anomalies, state changes, and predictive risk findings.

Stage A (observed) runs on the snapshot + learned baselines; stage B
(predictive) runs on the shared projections produced by prediction. Findings
are deterministic, evidence-carrying, and deduplicated by the service layer
into stable alerts. A data problem yields INSUFFICIENT_DATA / DATA_STALE
findings — never a fabricated clean bill of health.

Detector notes:

* **Demand spike/drop** — robust z-score of the prequential one-step error
  (median/MAD of recent errors, floor-scaled) with a materiality gate so
  tiny-but-unusual noise never alerts. Outage stations are censored: their
  drop is service failure, not a demand collapse.
* **Level shift** — the EWMA level ratio deviating persistently from 1.0;
  an indicator for forecast adaptation, not a probability.
* **Stockout / outage / route / depot / supply** — verified state facts.
* **Projected stockout / late replenishment** — from the shared projection,
  labeled PREDICTED, never fed back as an observed demand anomaly.
"""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass, field

from app.intelligence.config import PolicyConfig
from app.intelligence.forecaster import DemandModel, ForecastOutput, SeriesKey
from app.intelligence.models import (
    AnomalyKind,
    Confidence,
    DetectionResult,
    Evidence,
    Finding,
    FindingType,
    Severity,
)
from app.intelligence.projection import CellProjection
from app.intelligence.snapshot import Snapshot
from app.simulator.models import FuelType, SupplyArrivalStatus

_GRACE_TICKS = 1
_VOLUME_EPS = 1e-6


@dataclass
class ArrivalHistory:
    """Previously observed supply-arrival facts (for slippage/shortfall)."""

    planned_tick: dict[str, int] = field(default_factory=dict)
    quantity: dict[str, float] = field(default_factory=dict)


@dataclass
class DetectionInputs:
    snapshot: Snapshot
    policy: PolicyConfig
    model: DemandModel
    demand_rows: dict[SeriesKey, list[tuple[int, float]]]  # newest last
    forecasts: dict[SeriesKey, ForecastOutput]
    projections: dict[tuple[str, FuelType], CellProjection]
    arrival_history: ArrivalHistory
    stale_data: bool


def _finding(
    finding_type: FindingType,
    category: str,
    entity_ids: list[str],
    severity: Severity,
    confidence: Confidence,
    title: str,
    detail: str,
    tick: int,
    evidence: list[Evidence] | None = None,
    fuel: FuelType | None = None,
    hints: list[str] | None = None,
) -> Finding:
    return Finding(
        finding_id=f"{finding_type.value}:{':'.join(entity_ids)}:{fuel.value if fuel else 'ALL'}",
        type=finding_type,
        category=category,  # type: ignore[arg-type]
        entity_ids=entity_ids,
        fuel_type=fuel,
        severity=severity,
        confidence=confidence,
        title=title,
        detail=detail,
        evidence=evidence or [],
        recommendation_hints=hints or [],
        first_seen_tick=tick,
        last_seen_tick=tick,
        observed_at_epoch=time.time(),
    )


def _robust_z(value: float, residuals: list[float], floor: float) -> float:
    """Robust z-score using median/MAD with a positive scale floor."""
    if len(residuals) < 8:
        return 0.0
    center = statistics.median(residuals)
    mad = statistics.median([abs(r - center) for r in residuals])
    scale = max(1.4826 * mad, floor, 1.0)
    return (value - center) / scale


# ---------------------------------------------------------------------------
# Stage A: observed conditions
# ---------------------------------------------------------------------------


def detect_observed(inputs: DetectionInputs) -> list[Finding]:
    findings: list[Finding] = []
    snap = inputs.snapshot
    tick = snap.tick

    if inputs.stale_data:
        findings.append(
            _finding(
                FindingType.DATA_STALE,
                "ENGINEERING",
                ["simulator"],
                Severity.MEDIUM,
                Confidence.HIGH,
                "Simulator data is stale",
                "The snapshot is older than the configured freshness window (or the "
                "simulator reported stale data); dependent numeric outputs are degraded.",
                tick,
                [Evidence(name="snapshot_age_seconds", value=round(snap.age_seconds(), 1))],
                hints=["Require fresh data before approving or submitting any plan."],
            )
        )

    # -- station-level state, stockouts, demand anomalies ---------------------
    for station in snap.stations:
        open_for_service = station.status == "OPEN"
        if not open_for_service:
            findings.append(
                _finding(
                    FindingType.STATION_OUTAGE,
                    "OBSERVED",
                    [station.id],
                    Severity.HIGH,
                    Confidence.HIGH,
                    f"Station {station.id} is in OUTAGE",
                    "The station is not serving demand and must not receive allocations.",
                    tick,
                    [Evidence(name="status", value=station.status)],
                    hints=["Block new allocations; monitor for resolution."],
                )
            )

        for fuel in FuelType:
            key: SeriesKey = (station.id, fuel.value)
            inventory = station.inventory.get(fuel, 0.0)
            forecast = inputs.forecasts.get(key)
            next_demand = forecast.point[0] if forecast and forecast.point else None

            if (
                open_for_service
                and inventory <= _VOLUME_EPS
                and next_demand is not None
                and next_demand > _VOLUME_EPS
            ):
                findings.append(
                    _finding(
                        FindingType.CURRENT_STOCKOUT,
                        "OBSERVED",
                        [station.id],
                        Severity.CRITICAL,
                        Confidence.HIGH,
                        f"{station.id} is stocked out of {fuel.value}",
                        "Tank is empty while demand continues; every unmet liter is lost "
                        "demand until a delivery arrives.",
                        tick,
                        [
                            Evidence(name="inventory_liters", value=round(inventory, 1), unit="L"),
                            Evidence(
                                name="expected_next_tick_demand_liters",
                                value=round(next_demand, 1),
                                unit="L",
                            ),
                        ],
                        fuel=fuel,
                        hints=["Immediate dispatch from any feasible depot/route."],
                    )
                )

            anomaly = _demand_anomaly(inputs, station.id, fuel, next_demand or 0.0)
            if anomaly is None:
                continue
            if anomaly.kind is AnomalyKind.SPIKE:
                findings.append(
                    _finding(
                        FindingType.DEMAND_SPIKE,
                        "OBSERVED",
                        [station.id],
                        Severity.MEDIUM,
                        Confidence.MEDIUM,
                        f"Demand spike at {station.id} ({fuel.value})",
                        "The latest observation is a robust outlier above the prequential "
                        "baseline and is material relative to expected demand.",
                        tick,
                        [
                            Evidence(name="expected_liters", value=round(next_demand or 0.0, 1), unit="L"),
                            Evidence(name="observed_liters", value=round(anomaly.observed, 1), unit="L"),
                            Evidence(name="z_score", value=round(anomaly.z, 2)),
                        ],
                        fuel=fuel,
                        hints=["Re-check cover; consider an incremental delivery."],
                    )
                )
            else:
                findings.append(
                    _finding(
                        FindingType.DEMAND_DROP,
                        "OBSERVED",
                        [station.id],
                        Severity.LOW,
                        Confidence.MEDIUM,
                        f"Demand drop at {station.id} ({fuel.value})",
                        "The latest observation is a robust outlier below the baseline; "
                        "verify it is not censoring from an outage or stockout.",
                        tick,
                        [
                            Evidence(name="expected_liters", value=round(next_demand or 0.0, 1), unit="L"),
                            Evidence(name="observed_liters", value=round(anomaly.observed, 1), unit="L"),
                            Evidence(name="z_score", value=round(anomaly.z, 2)),
                        ],
                        fuel=fuel,
                    )
                )

    # -- level shifts (indicator only) ----------------------------------------
    for station in snap.stations:
        if station.status != "OPEN":
            continue
        for fuel in FuelType:
            forecast = inputs.forecasts.get((station.id, fuel.value))
            if forecast is None or forecast.ewma_level is None:
                continue
            threshold = inputs.policy.level_shift_z * 0.15  # alpha of the EWMA
            deviation = forecast.ewma_level - 1.0
            if abs(deviation) >= threshold:
                findings.append(
                    _finding(
                        FindingType.DEMAND_LEVEL_SHIFT,
                        "OBSERVED",
                        [station.id],
                        Severity.INFO,
                        Confidence.MEDIUM,
                        f"Demand level shift at {station.id} ({fuel.value})",
                        "Recent demand level persists above/below the seasonal profile; "
                        "the forecast has adapted and this finding is informational.",
                        tick,
                        [
                            Evidence(
                                name="ewma_level_ratio",
                                value=round(forecast.ewma_level, 3),
                                threshold=round(1.0 + math.copysign(threshold, deviation), 3),
                            )
                        ],
                        fuel=fuel,
                    )
                )

    # -- routes and depots -----------------------------------------------------
    for route in snap.routes:
        if route.status == "DISRUPTED":
            affected = sorted(
                {r.destination_station_id for r in snap.routes if r.id == route.id}
            )
            findings.append(
                _finding(
                    FindingType.ROUTE_BLOCKED,
                    "OBSERVED",
                    [route.id, *affected],
                    Severity.HIGH if affected else Severity.MEDIUM,
                    Confidence.HIGH,
                    f"Route {route.id} is DISRUPTED",
                    "The route cannot carry allocations until it returns to AVAILABLE.",
                    tick,
                    [Evidence(name="status", value=route.status)],
                    hints=["Exclude from planning; evaluate alternate routes."],
                )
            )
    for depot in snap.depots:
        if depot.status == "CONSTRAINED":
            findings.append(
                _finding(
                    FindingType.DEPOT_CONSTRAINT,
                    "OBSERVED",
                    [depot.id],
                    Severity.MEDIUM,
                    Confidence.HIGH,
                    f"Depot {depot.id} is CONSTRAINED",
                    "The depot remains shippable but is operating under a constraint "
                    "signal; watch its stock and dispatch headroom.",
                    tick,
                    [Evidence(name="status", value=depot.status)],
                )
            )

    # -- supply arrivals --------------------------------------------------------
    for arrival in snap.arrivals:
        prev_planned = inputs.arrival_history.planned_tick.get(arrival.id)
        prev_qty = inputs.arrival_history.quantity.get(arrival.id)
        not_arrived = arrival.status != SupplyArrivalStatus.ARRIVED
        if (
            prev_planned is not None
            and not_arrived
            and arrival.planned_tick > prev_planned
        ):
            findings.append(
                _finding(
                    FindingType.SUPPLY_ETA_SLIPPAGE,
                    "OBSERVED",
                    [arrival.id, arrival.depot_id],
                    Severity.MEDIUM,
                    Confidence.HIGH,
                    f"Supply {arrival.id} ETA slipped",
                    "The planned arrival tick moved later than previously observed.",
                    tick,
                    [
                        Evidence(name="previous_planned_tick", value=prev_planned),
                        Evidence(name="current_planned_tick", value=arrival.planned_tick),
                    ],
                    fuel=arrival.fuel_type,
                    hints=["Do not count this supply before the revised tick."],
                )
            )
        if (
            prev_qty is not None
            and not_arrived
            and arrival.quantity < prev_qty - _VOLUME_EPS
        ):
            findings.append(
                _finding(
                    FindingType.SUPPLY_SHORTFALL,
                    "OBSERVED",
                    [arrival.id, arrival.depot_id],
                    Severity.HIGH,
                    Confidence.HIGH,
                    f"Supply {arrival.id} quantity reduced",
                    "Confirmed incoming volume is smaller than previously observed.",
                    tick,
                    [
                        Evidence(name="previous_liters", value=round(prev_qty, 1), unit="L"),
                        Evidence(
                            name="current_liters", value=round(arrival.quantity, 1), unit="L"
                        ),
                    ],
                    fuel=arrival.fuel_type,
                )
            )
        if (
            arrival.status in (SupplyArrivalStatus.SCHEDULED, SupplyArrivalStatus.DELAYED)
            and tick > arrival.planned_tick + _GRACE_TICKS
        ):
            findings.append(
                _finding(
                    FindingType.SUPPLY_OVERDUE,
                    "OBSERVED",
                    [arrival.id, arrival.depot_id],
                    Severity.MEDIUM,
                    Confidence.HIGH,
                    f"Supply {arrival.id} is overdue",
                    "The planned tick passed with no confirmed arrival.",
                    tick,
                    [
                        Evidence(name="planned_tick", value=arrival.planned_tick),
                        Evidence(name="current_tick", value=tick),
                    ],
                    fuel=arrival.fuel_type,
                )
            )

    return findings


@dataclass
class AnomalySignal:
    kind: AnomalyKind
    z: float
    observed: float


def _demand_anomaly(
    inputs: DetectionInputs,
    station_id: str,
    fuel: FuelType,
    expected: float,
) -> AnomalySignal | None:
    """Compare the newest observation for this cell against the baseline.

    Uses the raw-demand robust z-score (median/MAD of prior observations at
    any tick) so it works before the trained model has residual history; the
    prequential error list sharpens it once available. Only the observation
    belonging to the current snapshot tick is tested, and never for outage
    stations (censored data).
    """
    if inputs.snapshot.station(station_id) is None:
        return None
    if inputs.snapshot.station(station_id).status != "OPEN":  # type: ignore[union-attr]
        return None
    rows = inputs.demand_rows.get((station_id, fuel.value))
    if not rows:
        return None
    obs_tick, value = rows[-1]
    if obs_tick != inputs.snapshot.tick:
        return None

    state = inputs.model.series.get((station_id, fuel.value))
    residuals = list(state.one_step_errors) if state else []
    history = [d for t, d in rows[:-1]][-48:]

    excess = value - expected
    material = abs(excess) >= inputs.policy.anomaly_materiality * max(expected, 1.0)
    if not material:
        return None

    if len(residuals) >= 8:
        center = statistics.median(residuals)
        mad = statistics.median([abs(r - center) for r in residuals])
        scale = max(1.4826 * mad, 0.05 * max(expected, 1.0), 1.0)
        z = (excess - center) / scale
    elif len(history) >= inputs.policy.anomaly_min_history:
        center = statistics.median(history)
        mad = statistics.median([abs(h - center) for h in history])
        scale = max(1.4826 * mad, 0.05 * max(expected, 1.0), 1.0)
        z = (value - center) / scale
    else:
        return None

    if z >= inputs.policy.anomaly_z_enter:
        return AnomalySignal(AnomalyKind.SPIKE, z, value)
    if z <= -inputs.policy.anomaly_z_enter:
        return AnomalySignal(AnomalyKind.DROP, z, value)
    return None


# ---------------------------------------------------------------------------
# Stage B: predictive findings (run after prediction on the same snapshot)
# ---------------------------------------------------------------------------


def detect_predictive(
    inputs: DetectionInputs,
    earliest_feasible_arrival: dict[tuple[str, FuelType], int | None],
) -> list[Finding]:
    findings: list[Finding] = []
    snap = inputs.snapshot
    policy = inputs.policy

    for (station_id, fuel), projection in inputs.projections.items():
        station = snap.station(station_id)
        if station is None or station.status != "OPEN":
            continue
        if projection.first_unmet_offset is None:
            continue
        unmet = projection.expected_unmet_physical_liters
        if unmet <= _VOLUME_EPS:
            continue

        forecast = inputs.forecasts.get((station_id, fuel.value))
        confidence = Confidence(forecast.confidence) if forecast else Confidence.LOW
        arrival = earliest_feasible_arrival.get((station_id, fuel))
        within = projection.first_unmet_offset <= policy.immediate_risk_horizon
        too_late = arrival is not None and projection.first_unmet_offset < arrival

        if too_late:
            findings.append(
                _finding(
                    FindingType.REPLENISHMENT_TOO_LATE,
                    "PREDICTED",
                    [station_id],
                    Severity.HIGH if within else Severity.MEDIUM,
                    confidence,
                    f"Earliest replenishment for {station_id} arrives after the projected shortage",
                    f"Shortage starts at +{projection.first_unmet_offset} ticks but the "
                    f"earliest feasible delivery lands at +{arrival} ticks; the early "
                    "unmet demand cannot be avoided by a new dispatch.",
                    snap.tick,
                    [
                        Evidence(name="first_unmet_offset", value=projection.first_unmet_offset, unit="ticks"),
                        Evidence(name="earliest_feasible_arrival_offset", value=arrival, unit="ticks"),
                    ],
                    fuel=fuel,
                )
            )
        elif within:
            findings.append(
                _finding(
                    FindingType.PROJECTED_STOCKOUT,
                    "PREDICTED",
                    [station_id],
                    Severity.HIGH,
                    confidence,
                    f"{station_id} projected to run short of {fuel.value} in "
                    f"{projection.first_unmet_offset} ticks",
                    f"Base-case projection shows ~{unmet:.0f}L unmet demand within the "
                    f"next {policy.immediate_risk_horizon} ticks without new action.",
                    snap.tick,
                    [
                        Evidence(name="expected_unmet_liters", value=round(unmet, 1), unit="L"),
                        Evidence(
                            name="first_unmet_offset",
                            value=projection.first_unmet_offset,
                            unit="ticks",
                        ),
                        Evidence(
                            name="current_inventory_liters",
                            value=projection.start_inventory_liters,
                            unit="L",
                        ),
                    ],
                    fuel=fuel,
                    hints=["Evaluate dispatch-now recommendations."],
                )
            )
        else:
            findings.append(
                _finding(
                    FindingType.PROJECTED_STOCKOUT,
                    "PREDICTED",
                    [station_id],
                    Severity.MEDIUM,
                    confidence,
                    f"{station_id} projected to run short of {fuel.value} in "
                    f"{projection.first_unmet_offset} ticks",
                    f"Base-case projection shows ~{unmet:.0f}L unmet demand at "
                    f"+{projection.first_unmet_offset} ticks; time remains to replenish.",
                    snap.tick,
                    [],
                    fuel=fuel,
                )
            )

        if arrival is None:
            findings.append(
                _finding(
                    FindingType.NO_TIMELY_REPLENISHMENT,
                    "PREDICTED",
                    [station_id],
                    Severity.HIGH,
                    Confidence.MEDIUM,
                    f"No feasible replenishment route for {station_id} ({fuel.value})",
                    "Projected unmet demand exists but no available depot/route pair can "
                    "deliver within the planning horizon.",
                    snap.tick,
                    [],
                    fuel=fuel,
                )
            )
    return findings


def build_detection_result(
    snapshot_id: str, tick: int, findings: list[Finding]
) -> DetectionResult:
    blocked: list[str] = []
    for f in findings:
        if f.type is FindingType.STATION_OUTAGE:
            for entity in f.entity_ids:
                if entity.startswith("station-"):
                    for fuel in FuelType:
                        blocked.append(f"{entity}:{fuel.value}")
    return DetectionResult(
        snapshot_id=snapshot_id,
        as_of_tick=tick,
        findings=findings,
        blocked_station_fuel=sorted(set(blocked)),
        generated_at_epoch=time.time(),
    )
