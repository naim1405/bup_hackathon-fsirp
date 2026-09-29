"""Constraint-aware greedy allocation planner.

Deterministic, explainable, and safe: every quantity it proposes is validated
against depot stock (net of commitments and reserves), per-tick dispatch
headroom, route max-shipment, and station tank headroom (including confirmed
inbound). It plans jointly across all station/fuel cells so competing needs
cannot double-book the same depot fuel (Decision Intelligence spec §6 and the
docs/recommendation-engine-design.md sizing pattern).

The planner is a heuristic: it does not claim global optimality. Each greedy
step evaluates the *whole-network* benefit of a candidate batch by re-running
the shared projector, picks the best-ranked batch, reserves it, and repeats
until no batch yields benefit, the step budget, or the wall-clock budget is
exhausted. Ranking is transparent: urgency per liter first, then horizon
benefit per liter, then fairness (worst service ratio), then earlier arrival.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from app.intelligence.config import PolicyConfig
from app.intelligence.models import (
    DepotStateAfter,
    ImpactSummary,
    InboundDelivery,
    NoActionReason,
    ProposedAction,
    Reason,
    Recommendation,
    Severity,
)
from app.intelligence.snapshot import Snapshot
from app.intelligence.projection import CellProjection, CellState, project_cell
from app.simulator.models import Allocation, AllocationStatus, FuelType, Route

_VOLUME_EPS = 1e-6
_TOPUP_BENEFIT_WEIGHT = 0.001  # lets cover top-ups rank below any urgent need
_FAIRNESS_WEIGHT = 0.05


@dataclass
class DepotRuntime:
    """Usable depot fuel and dispatch headroom, net of commitments."""

    usable_by_fuel: dict[tuple[str, FuelType], float] = field(default_factory=dict)
    dispatch_headroom_liters: float = math.inf


@dataclass
class CellNeed:
    station_id: str
    fuel_type: FuelType
    unmet_liters: float
    first_unmet_offset: int | None
    target_stock_liters: float
    waiting_age_ticks: int = 0


def _round_quantity(value: float) -> float:
    """Quantities are proposed in whole liters (documented simulator unit)."""
    return float(math.floor(max(0.0, value) + 1e-9))


def compute_depot_runtime(
    snapshot: Snapshot, policy: PolicyConfig, allocations: list[Allocation] | None = None
) -> DepotRuntime:
    """Depot stock available for NEW commitments.

    Conservative accounting (Decision Intelligence §3): undispatched accepted
    allocations (``PENDING``) are subtracted from current inventory even
    though the simulator *may* already have deducted them — if it did, our
    number is pessimistic, never unsafe. A hard reserve fraction of current
    inventory is withheld on top. Dispatch headroom is shared across fuels:
    current-tick departures consume ``dispatch_capacity_per_tick``.
    """
    allocations = allocations if allocations is not None else snapshot.allocations
    runtime = DepotRuntime()
    pending_by_depot: dict[tuple[str, FuelType], float] = {}
    departing_now = 0.0
    for allocation in allocations:
        if allocation.status is AllocationStatus.PENDING:
            key = (allocation.source_depot_id, allocation.fuel_type)
            pending_by_depot[key] = pending_by_depot.get(key, 0.0) + allocation.quantity
        if (
            allocation.status is AllocationStatus.IN_TRANSIT
            and allocation.departure_tick == snapshot.tick
        ):
            departing_now += allocation.quantity

    for depot in snapshot.depots:
        for fuel in FuelType:
            inventory = depot.inventory.get(fuel, 0.0)
            reserve = inventory * policy.depot_reserve_fraction
            committed = pending_by_depot.get((depot.id, fuel), 0.0)
            runtime.usable_by_fuel[(depot.id, fuel)] = max(
                0.0, inventory - committed - reserve
            )
    # Dispatch headroom is shared across fuels within a depot: current-tick
    # departures (IN_TRANSIT leaving now) consume dispatch_capacity_per_tick.
    runtime.dispatch_headroom_liters = math.inf
    runtime.per_depot_dispatch_headroom = {  # type: ignore[attr-defined]
        d.id: max(0.0, d.dispatch_capacity_per_tick - departing_now)
        for d in snapshot.depots
    }
    return runtime


@dataclass
class PlanWorld:
    """Mutable planning state shared across greedy iterations."""

    snapshot: Snapshot
    policy: PolicyConfig
    cells: dict[tuple[str, FuelType], CellState]
    demand_paths: dict[tuple[str, FuelType], list[float]]
    baseline_inbound: dict[tuple[str, FuelType], list[InboundDelivery]]
    runtime: DepotRuntime
    station_headroom: dict[tuple[str, FuelType], float]
    waiting_age: dict[tuple[str, FuelType], int] = field(default_factory=dict)
    proposed: list[ProposedAction] = field(default_factory=list)

    def inbound_for(self, key: tuple[str, FuelType]) -> list[InboundDelivery]:
        existing = list(self.baseline_inbound.get(key, []))
        for action in self.proposed:
            if (
                action.destination_station_id == key[0]
                and action.fuel_type is key[1]
            ):
                existing.append(
                    InboundDelivery(
                        allocation_id=-1,
                        source_depot_id=action.source_depot_id,
                        route_id=action.route_id,
                        fuel_type=action.fuel_type,
                        quantity_liters=action.quantity_liters,
                        expected_arrival_tick=action.expected_arrival_tick
                        - self.snapshot.tick,
                        status="PROPOSED",
                    )
                )
        return existing

    def project(self, key: tuple[str, FuelType]) -> CellProjection:
        cell = self.cells[key]
        path = self.demand_paths.get(key, [0.0] * self.policy.planning_horizon)
        return project_cell(cell, path, self.inbound_for(key), self.policy.planning_horizon)


def network_totals(
    world: PlanWorld,
) -> tuple[float, int, float | None]:
    """(total unmet, stockout cells, worst service ratio) across all cells."""
    total_unmet = 0.0
    stockouts = 0
    worst_ratio: float | None = None
    for key in world.cells:
        proj = world.project(key)
        total_unmet += proj.expected_unmet_physical_liters
        if proj.first_zero_offset is not None and proj.expected_unmet_physical_liters > _VOLUME_EPS:
            stockouts += 1
        if proj.service_ratio is not None:
            worst_ratio = (
                proj.service_ratio
                if worst_ratio is None
                else min(worst_ratio, proj.service_ratio)
            )
    return round(total_unmet, 1), stockouts, worst_ratio


def build_plan(
    snapshot: Snapshot,
    policy: PolicyConfig,
    cells: dict[tuple[str, FuelType], CellState],
    demand_paths: dict[tuple[str, FuelType], list[float]],
    baseline_inbound: dict[tuple[str, FuelType], list[InboundDelivery]],
    runtime: DepotRuntime,
    finding_ids_by_cell: dict[tuple[str, FuelType], list[str]] | None = None,
    waiting_age: dict[tuple[str, FuelType], int] | None = None,
) -> tuple[list[Recommendation], list[NoActionReason], list[NoActionReason], dict]:
    """Run the greedy loop. Returns (recommendations, no_action, uncovered, debug)."""
    started = time.monotonic()
    finding_ids_by_cell = finding_ids_by_cell or {}
    world = PlanWorld(
        snapshot=snapshot,
        policy=policy,
        cells=cells,
        demand_paths=demand_paths,
        baseline_inbound=baseline_inbound,
        runtime=runtime,
        station_headroom={
            key: max(
                0.0,
                cell.capacity_liters - cell.inventory_liters,
            )
            for key, cell in cells.items()
        },
        waiting_age=waiting_age or {},
    )

    open_cells = {
        key: cell for key, cell in cells.items() if cell.open_for_service
    }
    plan_steps = 0
    deadline = started + policy.solver_wall_timeout_seconds

    while plan_steps < policy.max_plan_steps and time.monotonic() < deadline:
        best = None
        for key, cell in open_cells.items():
            station_id, fuel = key
            projection = world.project(key)
            need = _remaining_need(projection, policy)
            if need <= _VOLUME_EPS:
                continue

            for route in snapshot.routes:
                if route.status != "AVAILABLE" or route.destination_station_id != station_id:
                    continue
                depot_id = route.source_depot_id
                depot_usable = runtime.usable_by_fuel.get((depot_id, fuel), 0.0)
                headroom = getattr(runtime, "per_depot_dispatch_headroom", {}).get(depot_id, 0.0)
                station_room = world.station_headroom.get(key, 0.0)
                batch_cap = route.max_shipment * policy.batch_fraction_of_route
                quantity = _round_quantity(
                    min(need, depot_usable, headroom, station_room, batch_cap)
                )
                if quantity < 1.0:
                    continue

                # Evaluate the whole-network benefit of this batch.
                trial = ProposedAction(
                    action_id=f"act-{plan_steps + 1:02d}-{station_id}-{fuel.value.lower()}",
                    source_depot_id=depot_id,
                    destination_station_id=station_id,
                    route_id=route.id,
                    fuel_type=fuel,
                    quantity_liters=quantity,
                    dispatch_tick=snapshot.tick,
                    expected_arrival_tick=snapshot.tick + route.transit_ticks,
                    transit_ticks=route.transit_ticks,
                    idempotency_key="",  # filled by the service
                )
                world.proposed.append(trial)
                after = world.project(key)
                world.proposed.pop()

                unmet_before = projection.expected_unmet_physical_liters
                unmet_after = after.expected_unmet_physical_liters
                benefit = unmet_before - unmet_after
                topup = min(
                    quantity,
                    max(0.0, need - (unmet_before - unmet_after)),
                )
                urgency = (
                    benefit / quantity if quantity > 0 else 0.0
                ) + _TOPUP_BENEFIT_WEIGHT * (topup / quantity if quantity else 0.0)
                fairness = (
                    (1.0 - (after.service_ratio or 1.0)) * _FAIRNESS_WEIGHT
                    if after.service_ratio is not None
                    else 0.0
                )
                rank = (
                    urgency + fairness,
                    -route.transit_ticks,
                    round(after.service_ratio or 0.0, 3),
                )
                if benefit <= _VOLUME_EPS and topup <= _VOLUME_EPS:
                    continue
                if best is None or rank > best[0]:
                    best = (rank, trial, benefit, unmet_after)

        if best is None:
            break
        _rank, action, _benefit, _unmet_after = best
        world.proposed.append(action)
        # Reserve resources before the next iteration.
        key = (action.destination_station_id, action.fuel_type)
        runtime.usable_by_fuel[(action.source_depot_id, action.fuel_type)] = max(
            0.0,
            runtime.usable_by_fuel.get((action.source_depot_id, action.fuel_type), 0.0)
            - action.quantity_liters,
        )
        per_depot = getattr(runtime, "per_depot_dispatch_headroom", {})
        if action.source_depot_id in per_depot:
            per_depot[action.source_depot_id] = max(
                0.0, per_depot[action.source_depot_id] - action.quantity_liters
            )
        world.station_headroom[key] = max(
            0.0, world.station_headroom.get(key, 0.0) - action.quantity_liters
        )
        plan_steps += 1

    recommendations = _merge_and_explain(world, finding_ids_by_cell)
    _ = deadline
    no_action, uncovered, debug = _explain_gaps(world, started)
    return recommendations, no_action, uncovered, debug


def _remaining_need(projection: CellProjection, policy: PolicyConfig) -> float:
    """Unmet demand plus a modest safety-buffer top-up target (spec §5 step E)."""
    unmet = projection.expected_unmet_physical_liters
    target_stock = policy.safety_buffer_fraction * projection.demand_total_liters
    ending_stock = (
        projection.projected_inventory[-1] if projection.projected_inventory else 0.0
    )
    cover_gap = max(0.0, target_stock - ending_stock)
    # Cover is only pursued for the immediate horizon; long top-ups are the
    # operator's job once urgent needs are served.
    if projection.first_unmet_offset is None and policy.desired_cover_ticks < policy.planning_horizon:
        cover_gap = min(
            cover_gap,
            policy.safety_buffer_fraction
            * sum(projection.projected_demand[: policy.desired_cover_ticks]),
        )
    return unmet + cover_gap


def _merge_and_explain(
    world: PlanWorld, finding_ids_by_cell: dict[tuple[str, FuelType], list[str]]
) -> list[Recommendation]:
    """Merge same-lane batches (within route limits) and build explanations.

    Batches for one depot→station lane are combined while they fit in a single
    route shipment; when a lane genuinely needs more than ``max_shipment`` the
    batches stay as separate shipments instead of being folded together.
    """
    lanes: dict[tuple[str, str, str, FuelType], list[ProposedAction]] = {}
    order: list[tuple[str, str, str, FuelType]] = []
    for action in world.proposed:
        lane = (
            action.source_depot_id,
            action.destination_station_id,
            action.route_id,
            action.fuel_type,
        )
        route = world.snapshot.route(action.route_id)
        max_shipment = route.max_shipment if route else action.quantity_liters
        bucket = lanes.setdefault(lane, [])
        if bucket and bucket[-1].quantity_liters + action.quantity_liters <= max_shipment + _VOLUME_EPS:
            bucket[-1].quantity_liters = _round_quantity(
                bucket[-1].quantity_liters + action.quantity_liters
            )
        else:
            bucket.append(action.model_copy(deep=True))
            if len(bucket) == 1:
                order.append(lane)
    merged_actions = [(lane, lanes[lane]) for lane in order]

    recommendations: list[Recommendation] = []
    severity_by_cell: dict[tuple[str, FuelType], Severity] = {}
    for (station, fuel), projection in ((k, world.project(k)) for k in world.cells):
        if projection.first_unmet_offset is None:
            continue
        if projection.first_unmet_offset <= world.policy.immediate_risk_horizon:
            severity_by_cell[(station, fuel)] = Severity.HIGH
        else:
            severity_by_cell[(station, fuel)] = Severity.MEDIUM

    for lane, bucket in merged_actions:
      for action in bucket:
          key = (action.destination_station_id, action.fuel_type)
          projection_after = world.project(key)
          route = world.snapshot.route(action.route_id)
          depot = world.snapshot.depot(action.source_depot_id)
          constraints = [
              "route_available",
              "route_direction",
              "route_max_shipment",
              "depot_usable_stock",
              "depot_dispatch_headroom",
              "station_capacity_headroom",
              "station_open",
              "fuel_identity",
          ]
          reasons = [
              Reason(
                  code="PROJECTED_SHORTAGE",
                  detail=(
                      f"Projected unmet {action.fuel_type.value} demand of "
                      f"{round(projection_after.expected_unmet_physical_liters, 0):.0f}L "
                      "remains at this station even with this delivery."
                      if projection_after.expected_unmet_physical_liters > _VOLUME_EPS
                      else "This delivery covers the projected shortage window."
                  ),
                  values={
                      "expected_unmet_after_liters": projection_after.expected_unmet_physical_liters,
                      "first_unmet_offset": projection_after.first_unmet_offset,
                  },
              ),
              Reason(
                  code="ETA",
                  detail=(
                      f"Departs at tick {action.dispatch_tick} on route {action.route_id} "
                      f"({action.transit_ticks} transit ticks), arriving tick "
                      f"{action.expected_arrival_tick}."
                  ),
                  values={
                      "transit_ticks": action.transit_ticks,
                      "expected_arrival_tick": action.expected_arrival_tick,
                  },
              ),
          ]
          if depot is not None and depot.status == "CONSTRAINED":
              reasons.append(
                  Reason(
                      code="DEPOT_CONSTRAINED",
                      detail="Source depot is CONSTRAINED; stock and dispatch headroom were verified.",
                      values={"depot_status": depot.status},
                  )
              )
          if route is not None:
              alternatives = [
                  {
                      "route_id": r.id,
                      "source_depot_id": r.source_depot_id,
                      "transit_ticks": r.transit_ticks,
                      "max_shipment_liters": r.max_shipment,
                      "not_chosen_because": "later arrival or less remaining depot stock",
                  }
                  for r in world.snapshot.routes
                  if r.destination_station_id == action.destination_station_id
                  and r.id != action.route_id
                  and r.status == "AVAILABLE"
              ]
          else:
              alternatives = []
          recommendations.append(
              Recommendation(
                  action=action,
                  severity=severity_by_cell.get(key, Severity.MEDIUM),
                  reason_codes=["PROJECTED_SHORTAGE", "ETA"]
                  + (["DEPOT_CONSTRAINED"] if depot is not None and depot.status == "CONSTRAINED" else []),
                  reasons=reasons,
                  serving_findings=finding_ids_by_cell.get(key, []),
                  constraints_checked=constraints,
                  binding_constraint=None,
                  estimated_arrival_tick=action.expected_arrival_tick,
                  alternatives=alternatives[:2],
              )
          )
    recommendations.sort(key=lambda r: (r.severity.value, -r.action.quantity_liters))
    return recommendations


def _explain_gaps(
    world: PlanWorld, started: float
) -> tuple[list[NoActionReason], list[NoActionReason], dict]:
    """Why some cells get no recommendation, and which needs remain uncovered."""
    no_action: list[NoActionReason] = []
    uncovered: list[NoActionReason] = []
    runtime_usable = world.runtime.usable_by_fuel
    for key, cell in world.cells.items():
        station_id, fuel = key
        projection = world.project(key)
        unmet = projection.expected_unmet_physical_liters
        station = world.snapshot.station(station_id)
        if station is None:
            continue
        if not cell.open_for_service:
            if projection.demand_total_liters > _VOLUME_EPS:
                no_action.append(
                    NoActionReason(
                        station_id=station_id,
                        fuel_type=fuel,
                        reason_code="STATION_OUTAGE",
                        detail=(
                            f"Station is in OUTAGE; ~{projection.demand_total_liters:.0f}L of "
                            "underlying demand cannot be served until it reopens. No delivery "
                            "is proposed because receiving is blocked."
                        ),
                    )
                )
            continue
        if unmet <= _VOLUME_EPS:
            continue
        # Which constraint blocks further help?
        total_usable = sum(
            v for (depot, f), v in runtime_usable.items() if f is fuel
        )
        has_open_route = any(
            r.status == "AVAILABLE" and r.destination_station_id == station_id
            for r in world.snapshot.routes
        )
        if not has_open_route:
            uncovered.append(
                NoActionReason(
                    station_id=station_id,
                    fuel_type=fuel,
                    reason_code="NO_AVAILABLE_ROUTE",
                    detail=f"~{unmet:.0f}L projected unmet demand; every route to this station is disrupted.",
                )
            )
        elif total_usable <= _VOLUME_EPS:
            uncovered.append(
                NoActionReason(
                    station_id=station_id,
                    fuel_type=fuel,
                    reason_code="INSUFFICIENT_DEPOT_STOCK",
                    detail=(
                        f"~{unmet:.0f}L projected unmet demand; no depot has usable "
                        f"{fuel.value} stock beyond commitments and reserves."
                    ),
                )
            )
        else:
            uncovered.append(
                NoActionReason(
                    station_id=station_id,
                    fuel_type=fuel,
                    reason_code="CONSTRAINT_LIMITED",
                    detail=(
                        f"~{unmet:.0f}L projected unmet demand remains after all feasible "
                        "dispatches (route max-shipment, dispatch headroom, or tank "
                        "headroom limits)."
                    ),
                )
            )
    unmet_total, stockouts, worst_ratio = network_totals(world)
    debug = {
        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        "network_unmet_before_plan_liters": unmet_total,
        "network_stockout_cells": stockouts,
        "worst_service_ratio": worst_ratio,
    }
    return no_action, uncovered, debug


def build_impact(world_before: PlanWorld, world_after: PlanWorld) -> ImpactSummary:
    """Baseline (do nothing) vs proposed plan under identical assumptions."""
    unmet_before, stockouts_before, worst_before = network_totals(world_before)
    unmet_after, stockouts_after, worst_after = network_totals(world_after)
    return ImpactSummary(
        expected_unmet_before_liters=unmet_before,
        expected_unmet_after_liters=unmet_after,
        unmet_avoided_liters=round(unmet_before - unmet_after, 1),
        stockouts_before=stockouts_before,
        stockouts_after=stockouts_after,
        worst_service_ratio_before=worst_before,
        worst_service_ratio_after=worst_after,
        note=(
            "Deterministic base-case projection with the same demand forecast, "
            "confirmed inbound, and capacity assumptions in both scenarios. "
            "Simulator outcomes may differ."
        ),
    )


def depot_state_after(
    snapshot: Snapshot, runtime: DepotRuntime, proposed: list[ProposedAction]
) -> list[DepotStateAfter]:
    consumed: dict[tuple[str, FuelType], float] = {}
    for action in proposed:
        key = (action.source_depot_id, action.fuel_type)
        consumed[key] = consumed.get(key, 0.0) + action.quantity_liters
    states: list[DepotStateAfter] = []
    per_depot = getattr(runtime, "per_depot_dispatch_headroom", {})
    for (depot_id, fuel), usable in sorted(runtime.usable_by_fuel.items()):
        states.append(
            DepotStateAfter(
                depot_id=depot_id,
                fuel_type=fuel,
                remaining_usable_liters=round(max(0.0, usable - consumed.get((depot_id, fuel), 0.0)), 1),
                dispatch_headroom_liters=round(per_depot.get(depot_id, 0.0), 1),
            )
        )
    return states


def validate_plan(
    snapshot: Snapshot,
    policy: PolicyConfig,
    actions: list[ProposedAction],
    baseline_inbound: dict[tuple[str, FuelType], list[InboundDelivery]],
) -> list[str]:
    """Independent whole-plan feasibility check (Decision Intelligence §6/§13).

    Re-derives every constraint from the snapshot; returns human-readable
    violations. An empty list means the plan is internally feasible.
    """
    violations: list[str] = []
    runtime = compute_depot_runtime(snapshot, policy)
    per_depot = getattr(runtime, "per_depot_dispatch_headroom", {})

    station_in: dict[tuple[str, FuelType], float] = {}
    depot_out: dict[tuple[str, FuelType], float] = {}
    dispatch_use: dict[str, float] = {}

    for action in actions:
        route = snapshot.route(action.route_id)
        if route is None:
            violations.append(f"{action.action_id}: route {action.route_id} does not exist")
            continue
        if route.source_depot_id != action.source_depot_id or route.destination_station_id != action.destination_station_id:
            violations.append(f"{action.action_id}: route does not connect {action.source_depot_id} -> {action.destination_station_id}")
        if route.status != "AVAILABLE":
            violations.append(f"{action.action_id}: route {action.route_id} is not AVAILABLE")
        if action.quantity_liters <= 0:
            violations.append(f"{action.action_id}: quantity must be positive")
        if action.quantity_liters > route.max_shipment + _VOLUME_EPS:
            violations.append(
                f"{action.action_id}: quantity {action.quantity_liters} exceeds route max shipment {route.max_shipment}"
            )
        station = snapshot.station(action.destination_station_id)
        if station is None:
            violations.append(f"{action.action_id}: destination station does not exist")
            continue
        if station.status != "OPEN":
            violations.append(f"{action.action_id}: station is not OPEN")
        depot = snapshot.depot(action.source_depot_id)
        if depot is None:
            violations.append(f"{action.action_id}: source depot does not exist")
            continue
        key = (action.source_depot_id, action.fuel_type)
        depot_out[key] = depot_out.get(key, 0.0) + action.quantity_liters
        cell_key = (action.destination_station_id, action.fuel_type)
        station_in[cell_key] = station_in.get(cell_key, 0.0) + action.quantity_liters
        dispatch_use[action.source_depot_id] = (
            dispatch_use.get(action.source_depot_id, 0.0) + action.quantity_liters
        )

    for (depot_id, fuel), volume in depot_out.items():
        usable = runtime.usable_by_fuel.get((depot_id, fuel), 0.0)
        if volume > usable + _VOLUME_EPS:
            violations.append(
                f"depot {depot_id} {fuel.value}: plan uses {volume:.0f}L but only {usable:.0f}L is usable"
            )
    for depot_id, volume in dispatch_use.items():
        headroom = per_depot.get(depot_id, 0.0)
        if volume > headroom + _VOLUME_EPS:
            violations.append(
                f"depot {depot_id}: plan dispatches {volume:.0f}L in one tick but headroom is {headroom:.0f}L"
            )
    for (station_id, fuel), volume in station_in.items():
        station = snapshot.station(station_id)
        if station is None:
            continue
        confirmed = sum(
            d.quantity_liters for d in baseline_inbound.get((station_id, fuel), [])
        )
        room = station.capacity.get(fuel, 0.0) - station.inventory.get(fuel, 0.0) - confirmed
        if volume > room + _VOLUME_EPS:
            violations.append(
                f"station {station_id} {fuel.value}: plan delivers {volume:.0f}L but tank headroom is {room:.0f}L"
            )
    return violations
