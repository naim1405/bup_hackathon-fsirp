"""Tests for the constrained greedy allocator.

Includes the specification's numerical sanity example (§12) and the
"two candidates cannot double-book depot stock" acceptance case.
"""

from __future__ import annotations

import pytest

from app.intelligence import allocator
from app.intelligence.config import PolicyConfig
from app.intelligence.models import InboundDelivery, ProposedAction
from app.intelligence.snapshot import Snapshot, StationContext, WorldContext
from app.simulator.models import (
    Allocation,
    AllocationStatus,
    Depot,
    DomainEvent,
    FuelType,
    Region,
    Route,
    SimulatorInstance,
    Station,
    SupplyArrival,
)

from datetime import datetime, timezone


def instance(tick: int = 100) -> SimulatorInstance:
    return SimulatorInstance(
        id=1,
        scenario_id="baseline",
        scenario_version="1.0.0",
        seed=42,
        sim_time=datetime.now(timezone.utc),
        tick=tick,
        tick_minutes=15,
        status="RUNNING",
    )


def depot(depot_id: str, diesel: float, dispatch_per_tick: float = 12_000.0, status: str = "OPEN") -> Depot:
    return Depot(
        id=depot_id,
        name=depot_id,
        region_id="region-dhaka",
        status=status,  # type: ignore[arg-type]
        dispatch_capacity_per_tick=dispatch_per_tick,
        capacity={f: 100_000.0 for f in FuelType},
        inventory={f: 0.0 for f in FuelType} | {FuelType.DIESEL: diesel},
    )


def station(station_id: str, diesel_inventory: float, diesel_capacity: float = 20_000.0, status: str = "OPEN") -> Station:
    return Station(
        id=station_id,
        name=station_id,
        region_id="region-dhaka",
        status=status,  # type: ignore[arg-type]
        demand_profile="urban_high",
        demand_multiplier=1.0,
        capacity={f: 10_000.0 for f in FuelType} | {FuelType.DIESEL: diesel_capacity},
        inventory={f: 1_000.0 for f in FuelType} | {FuelType.DIESEL: diesel_inventory},
    )


def route(route_id: str, src: str, dst: str, transit: int = 2, max_shipment: float = 7_000.0, status: str = "AVAILABLE") -> Route:
    return Route(
        id=route_id,
        source_depot_id=src,
        destination_station_id=dst,
        transit_ticks=transit,
        max_shipment=max_shipment,
        status=status,  # type: ignore[arg-type]
    )


def make_snapshot(
    *,
    tick: int = 100,
    depots: list[Depot] | None = None,
    stations: list[Station] | None = None,
    routes: list[Route] | None = None,
    allocations: list[Allocation] | None = None,
) -> Snapshot:
    depots = depots or [depot("depot-1", 900.0)]
    stations = stations or [
        station("station-a", 100.0, diesel_capacity=1_000.0),
        station("station-b", 100.0, diesel_capacity=1_000.0),
    ]
    routes = routes or [
        route("route-a", "depot-1", "station-a"),
        route("route-b", "depot-1", "station-b"),
    ]
    snap = Snapshot(
        run_id="1:baseline:1.0.0:42",
        tick=tick,
        fetched_at_epoch=0.0,
        instance=instance(tick),
        health=None,
        regions=[Region(id="region-dhaka", name="Dhaka", demand_factor=1.0)],
        depots=depots,
        stations=stations,
        routes=routes,
        arrivals=[],
        events=[],
        allocations=allocations or [],
    )
    return snap


def policy(**overrides: object) -> PolicyConfig:
    defaults: dict[str, object] = {
        "planning_horizon": 6,
        "immediate_risk_horizon": 6,
        "depot_reserve_fraction": 0.0,
        "solver_wall_timeout_seconds": 2.0,
        "batch_fraction_of_route": 0.5,
        "safety_buffer_fraction": 0.0,
    }
    defaults.update(overrides)
    return PolicyConfig(**defaults)  # type: ignore[arg-type]


def run_planner(
    snap: Snapshot,
    pol: PolicyConfig,
    demand: dict[str, list[float]] | None = None,
    horizon: int = 6,
):
    pol.planning_horizon = horizon
    cells = {}
    paths = {}
    inbound: dict[tuple[str, FuelType], list[InboundDelivery]] = {}
    for s in snap.stations:
        for fuel in FuelType:
            key = (s.id, fuel)
            cells[key] = allocator.CellState(
                station_id=s.id,
                fuel_type=fuel,
                inventory_liters=s.inventory.get(fuel, 0.0),
                capacity_liters=s.capacity.get(fuel, 0.0),
                open_for_service=s.status == "OPEN",
                accepts_deliveries=s.status == "OPEN",
            )
            # Only DIESEL is under stress in these fixtures; other fuels idle.
            paths[key] = list((demand or {}).get(s.id, [0.0] * horizon)) if fuel is FuelType.DIESEL else [0.0] * horizon
            inbound[key] = []
    runtime = allocator.compute_depot_runtime(snap, pol)
    recs, no_action, uncovered, debug = allocator.build_plan(
        snap, pol, cells, paths, inbound, runtime
    )
    return recs, no_action, uncovered, debug, cells, paths, inbound, runtime


class TestSpecSanityExample:
    def test_minimal_shortage_eliminating_plan(self) -> None:
        """§12: depot 900L; A needs 500, B needs 200 → plan ships 500+200."""
        snap = make_snapshot(
            depots=[depot("depot-1", 900.0)],
            stations=[
                station("station-a", 100.0, diesel_capacity=1_000.0),
                station("station-b", 100.0, diesel_capacity=1_000.0),
            ],
            routes=[
                route("route-a", "depot-1", "station-a", transit=1, max_shipment=7_000.0),
                route("route-b", "depot-1", "station-b", transit=1, max_shipment=6_500.0),
            ],
        )
        pol = policy(planning_horizon=3)
        recs, _no, uncovered, _dbg, _cells, _paths, _inbound, _rt = run_planner(
            snap,
            pol,
            demand={"station-a": [200.0, 200.0, 200.0], "station-b": [100.0, 100.0, 100.0]},
            horizon=3,
        )
        by_station = {r.action.destination_station_id: r.action.quantity_liters for r in recs}
        assert by_station.get("station-a") == 500.0
        assert by_station.get("station-b") == 200.0
        assert uncovered == [] or all(u.reason_code == "CONSTRAINT_LIMITED" for u in uncovered)

    def test_largest_demand_does_not_consume_everything(self) -> None:
        """Giving A all 900L would violate A's receiving headroom and starve B."""
        snap = make_snapshot(
            depots=[depot("depot-1", 900.0)],
            stations=[
                station("station-a", 100.0, diesel_capacity=700.0),
                station("station-b", 100.0, diesel_capacity=1_000.0),
            ],
            routes=[
                route("route-a", "depot-1", "station-a", transit=1, max_shipment=7_000.0),
                route("route-b", "depot-1", "station-b", transit=1, max_shipment=6_500.0),
            ],
        )
        pol = policy(planning_horizon=3)
        recs, _no, _unc, _dbg, _cells, _paths, _inbound, _rt = run_planner(
            snap,
            pol,
            demand={"station-a": [200.0, 200.0, 200.0], "station-b": [100.0, 100.0, 100.0]},
            horizon=3,
        )
        to_a = next((r for r in recs if r.action.destination_station_id == "station-a"), None)
        to_b = next((r for r in recs if r.action.destination_station_id == "station-b"), None)
        assert to_a is not None and to_a.action.quantity_liters <= 600.0
        assert to_b is not None, "station B must not be starved"

    def test_insufficient_supply_is_disclosed(self) -> None:
        """400 usable against 700 need → uncovered demand is reported."""
        snap = make_snapshot(
            depots=[depot("depot-1", 400.0)],
            stations=[
                station("station-a", 100.0, diesel_capacity=1_000.0),
                station("station-b", 100.0, diesel_capacity=1_000.0),
            ],
            routes=[
                route("route-a", "depot-1", "station-a", transit=1),
                route("route-b", "depot-1", "station-b", transit=1),
            ],
        )
        pol = policy(planning_horizon=3)
        recs, _no, uncovered, _dbg, _c, _p, _i, _rt = run_planner(
            snap,
            pol,
            demand={"station-a": [200.0, 200.0, 200.0], "station-b": [100.0, 100.0, 100.0]},
            horizon=3,
        )
        shipped = sum(r.action.quantity_liters for r in recs)
        assert shipped <= 400.0
        assert any(u.reason_code in ("INSUFFICIENT_DEPOT_STOCK", "CONSTRAINT_LIMITED") for u in uncovered)


class TestConstraints:
    def test_competing_candidates_cannot_double_book_depot(self) -> None:
        """C4: the same 600 usable liters cannot fund two 600 allocations."""
        snap = make_snapshot(
            depots=[depot("depot-1", 600.0)],
            stations=[
                station("station-a", 0.0, diesel_capacity=2_000.0),
                station("station-b", 0.0, diesel_capacity=2_000.0),
            ],
            routes=[
                route("route-a", "depot-1", "station-a", transit=1, max_shipment=7_000.0),
                route("route-b", "depot-1", "station-b", transit=1, max_shipment=7_000.0),
            ],
        )
        pol = policy(planning_horizon=4)
        recs, _no, _unc, _dbg, _c, _p, _i, _rt = run_planner(
            snap, pol, demand={"station-a": [150.0] * 4, "station-b": [150.0] * 4}, horizon=4
        )
        total = sum(r.action.quantity_liters for r in recs)
        assert total <= 600.0 + 1e-6
        actions = [r.action for r in recs]
        assert allocator.validate_plan(snap, pol, actions, {}) == []

    def test_outage_station_receives_nothing(self) -> None:
        snap = make_snapshot(
            stations=[station("station-a", 0.0, status="OUTAGE"), station("station-b", 500.0)],
            routes=[route("route-a", "depot-1", "station-a"), route("route-b", "depot-1", "station-b")],
        )
        pol = policy()
        recs, no_action, _unc, _dbg, _c, _p, _i, _rt = run_planner(
            snap, pol, demand={"station-a": [100.0] * 6, "station-b": [10.0] * 6}
        )
        assert all(r.action.destination_station_id != "station-a" for r in recs)
        assert any(n.station_id == "station-a" and n.reason_code == "STATION_OUTAGE" for n in no_action)

    def test_disrupted_route_excluded(self) -> None:
        snap = make_snapshot(
            stations=[station("station-a", 0.0)],
            routes=[route("route-a", "depot-1", "station-a", status="DISRUPTED")],
        )
        pol = policy()
        recs, _no, uncovered, _dbg, _c, _p, _i, _rt = run_planner(
            snap, pol, demand={"station-a": [100.0] * 6}
        )
        assert recs == []
        assert any(u.reason_code == "NO_AVAILABLE_ROUTE" for u in uncovered)

    def test_pending_commitments_reduce_usable_stock(self) -> None:
        """C8: accepted PENDING allocations are subtracted exactly once."""
        snap = make_snapshot(
            depots=[depot("depot-1", 600.0)],
            allocations=[
                Allocation(
                    id=1,
                    idempotency_key="run:plan:act",
                    source_depot_id="depot-1",
                    destination_station_id="station-x",
                    route_id="route-a",
                    fuel_type=FuelType.DIESEL,
                    quantity=250.0,
                    created_tick=90,
                    status=AllocationStatus.PENDING,
                )
            ],
        )
        runtime = allocator.compute_depot_runtime(snap, policy())
        assert runtime.usable_by_fuel[("depot-1", FuelType.DIESEL)] == pytest.approx(350.0)

    def test_validator_catches_bad_plans(self) -> None:
        snap = make_snapshot()
        pol = policy()
        bad = [
            ProposedAction(
                action_id="a1",
                source_depot_id="depot-1",
                destination_station_id="station-b",  # wrong direction for route-a
                route_id="route-a",
                fuel_type=FuelType.DIESEL,
                quantity_liters=100.0,
                dispatch_tick=100,
                expected_arrival_tick=102,
                transit_ticks=2,
                idempotency_key="k1",
            )
        ]
        violations = allocator.validate_plan(snap, pol, bad, {})
        assert any("does not connect" in v for v in violations)

        over = [
            ProposedAction(
                action_id="a2",
                source_depot_id="depot-1",
                destination_station_id="station-a",
                route_id="route-a",
                fuel_type=FuelType.DIESEL,
                quantity_liters=999_999.0,
                dispatch_tick=100,
                expected_arrival_tick=102,
                transit_ticks=2,
                idempotency_key="k2",
            )
        ]
        violations = allocator.validate_plan(snap, pol, over, {})
        assert any("max shipment" in v or "usable" in v for v in violations)

    def test_reserve_is_enforced(self) -> None:
        pol = policy(depot_reserve_fraction=0.5)
        snap = make_snapshot(depots=[depot("depot-1", 600.0)])
        runtime = allocator.compute_depot_runtime(snap, pol)
        assert runtime.usable_by_fuel[("depot-1", FuelType.DIESEL)] == pytest.approx(300.0)


class TestLaneMerging:
    def test_same_lane_batches_merge_within_route_limit(self) -> None:
        snap = make_snapshot(
            depots=[depot("depot-1", 3_000.0)],
            stations=[station("station-a", 0.0, diesel_capacity=10_000.0)],
            routes=[route("route-a", "depot-1", "station-a", transit=1, max_shipment=7_000.0)],
        )
        pol = policy(batch_fraction_of_route=0.1, planning_horizon=6)
        recs, _no, _unc, _dbg, _c, _p, _i, _rt = run_planner(
            snap, pol, demand={"station-a": [500.0] * 6}, horizon=6
        )
        diesel_rows = [r for r in recs if r.action.fuel_type is FuelType.DIESEL]
        assert diesel_rows, "need must produce a plan"
        # All diesel quantity lands in ONE shipment when it fits the route.
        assert len(diesel_rows) == 1
        assert diesel_rows[0].action.quantity_liters <= 7_000.0

    def test_oversubscribed_lane_splits_into_distinct_shipments(self) -> None:
        """A lane needing more than max_shipment yields distinct shipments, and
        never the same action twice (regression for the merge-replace bug)."""
        snap = make_snapshot(
            depots=[depot("depot-1", 12_000.0)],
            stations=[station("station-a", 0.0, diesel_capacity=20_000.0)],
            routes=[route("route-a", "depot-1", "station-a", transit=1, max_shipment=3_000.0)],
        )
        pol = policy(batch_fraction_of_route=0.5, planning_horizon=12)
        recs, _no, _unc, _dbg, _c, _p, _i, _rt = run_planner(
            snap, pol, demand={"station-a": [900.0] * 12}, horizon=12
        )
        rows = [r for r in recs if r.action.fuel_type is FuelType.DIESEL]
        ids = [r.action.action_id for r in rows]
        assert len(ids) == len(set(ids)), f"duplicate action rows: {ids}"
        for row in rows:
            assert row.action.quantity_liters <= 3_000.0 + 1e-6
        assert sum(r.action.quantity_liters for r in rows) >= 5_000.0
