"""End-to-end engine tests against an in-process fake simulator.

Covers the full loop: bootstrap training from historical data → forecast →
detect → plan → approve → submit (with idempotency keys) → reconcile
ambiguous outcomes → run reset → degraded behavior on upstream failure.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from app.intelligence.config import PolicyConfig
from app.intelligence.service import IntelligenceEngine
from app.intelligence.models import PlanStatus, RejectionReason
from app.simulator.models import FuelType


TICK_MINUTES = 15
START_TICK = 200


def demand_at(tick: int, base: float) -> float:
    """Deterministic daily pattern: busy 'day', quiet 'night'."""
    tod = tick % 96
    factor = 1.5 if 24 <= tod < 72 else 0.6
    noise = ((tick * 37) % 11 - 5) / 100.0  # ±5%
    return max(1.0, base * factor * (1.0 + noise))


class FakeSimulator:
    """A tiny deterministic clone of the BUP simulator's public API."""

    def __init__(self) -> None:
        self.instance_id = 1
        self.tick = START_TICK
        self.paused = False
        self.fail_next_post = False
        self.malformed_post_response = False
        self.stale = False
        self.fail_station_history = False
        self.break_reads = False
        self.next_allocation_id = 5000
        self.allocations: list[dict[str, Any]] = []
        self.post_bodies: list[dict[str, Any]] = []
        self.base = {
            "station-mirpur": {"DIESEL": 95.0, "PETROL": 110.0, "OCTANE": 55.0},
            "station-tongi": {"DIESEL": 140.0, "PETROL": 45.0, "OCTANE": 22.0},
            "station-karnaphuli": {"DIESEL": 85.0, "PETROL": 90.0, "OCTANE": 48.0},
            "station-coxsbazar": {"DIESEL": 70.0, "PETROL": 72.0, "OCTANE": 35.0},
        }
        self.capacity = {
            "station-mirpur": {"DIESEL": 15_000.0, "PETROL": 14_000.0, "OCTANE": 9_000.0},
            "station-tongi": {"DIESEL": 18_000.0, "PETROL": 9_000.0, "OCTANE": 6_000.0},
            "station-karnaphuli": {"DIESEL": 14_000.0, "PETROL": 15_000.0, "OCTANE": 9_000.0},
            "station-coxsbazar": {"DIESEL": 12_000.0, "PETROL": 12_000.0, "OCTANE": 7_000.0},
        }
        self.inventory: dict[str, dict[str, float]] = {}
        for station, fuels in self.base.items():
            self.inventory[station] = {f: 9_000.0 for f in fuels}
        self.depots = {
            "depot-gazipur": {"DIESEL": 60_000.0, "PETROL": 45_000.0, "OCTANE": 26_000.0},
            "depot-patiya": {"DIESEL": 55_000.0, "PETROL": 42_000.0, "OCTANE": 24_000.0},
        }
        self.routes = [
            {"id": "route-gazipur-mirpur", "source_depot_id": "depot-gazipur", "destination_station_id": "station-mirpur", "transit_ticks": 2, "max_shipment": 7000.0, "status": "AVAILABLE"},
            {"id": "route-gazipur-tongi", "source_depot_id": "depot-gazipur", "destination_station_id": "station-tongi", "transit_ticks": 2, "max_shipment": 6500.0, "status": "AVAILABLE"},
            {"id": "route-patiya-karnaphuli", "source_depot_id": "depot-patiya", "destination_station_id": "station-karnaphuli", "transit_ticks": 2, "max_shipment": 7000.0, "status": "AVAILABLE"},
            {"id": "route-patiya-coxsbazar", "source_depot_id": "depot-patiya", "destination_station_id": "station-coxsbazar", "transit_ticks": 3, "max_shipment": 6000.0, "status": "AVAILABLE"},
            {"id": "route-gazipur-karnaphuli", "source_depot_id": "depot-gazipur", "destination_station_id": "station-karnaphuli", "transit_ticks": 4, "max_shipment": 5000.0, "status": "AVAILABLE"},
            {"id": "route-patiya-mirpur", "source_depot_id": "depot-patiya", "destination_station_id": "station-mirpur", "transit_ticks": 4, "max_shipment": 5000.0, "status": "AVAILABLE"},
        ]
        # 10 days of demand history for training (12 rows per tick).
        self.demand_rows: list[dict[str, Any]] = []
        for tick in range(0, START_TICK):
            for station, fuels in self.base.items():
                for fuel, base in fuels.items():
                    self.demand_rows.append(
                        {
                            "id": len(self.demand_rows) + 1,
                            "station_id": station,
                            "fuel_type": fuel,
                            "tick": tick,
                            "sim_time": self._sim_time(tick).isoformat(),
                            "demand_liters": demand_at(tick, base),
                            "served_liters": demand_at(tick, base),
                            "unmet_liters": 0.0,
                        }
                    )
        self.arrivals = [
            {
                "id": "arr-1",
                "depot_id": "depot-gazipur",
                "fuel_type": "DIESEL",
                "quantity": 30_000.0,
                "planned_tick": START_TICK + 10,
                "actual_tick": None,
                "status": "SCHEDULED",
            }
        ]
        self.events: list[dict[str, Any]] = []

    # -- world helpers ------------------------------------------------------

    def _sim_time(self, tick: int) -> datetime:
        return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=tick * TICK_MINUTES)

    def advance(self, ticks: int = 1) -> None:
        for _ in range(ticks):
            self.tick += 1
            for station, fuels in self.base.items():
                for fuel, base in fuels.items():
                    want = demand_at(self.tick, base)
                    have = self.inventory[station][fuel]
                    served = min(want, have)
                    self.demand_rows.append(
                        {
                            "id": len(self.demand_rows) + 1,
                            "station_id": station,
                            "fuel_type": fuel,
                            "tick": self.tick,
                            "sim_time": self._sim_time(self.tick).isoformat(),
                            "demand_liters": want,
                            "served_liters": served,
                            "unmet_liters": want - served,
                        }
                    )
                    self.inventory[station][fuel] = have - served
            # Deliver in-transit allocations.
            for allocation in self.allocations:
                if (
                    allocation["status"] == "IN_TRANSIT"
                    and allocation["expected_arrival_tick"] is not None
                    and self.tick >= allocation["expected_arrival_tick"]
                ):
                    allocation["status"] = "ARRIVED"
                    allocation["actual_arrival_tick"] = self.tick
                    self.inventory[allocation["destination_station_id"]][allocation["fuel_type"]] = min(
                        self.capacity[allocation["destination_station_id"]][allocation["fuel_type"]],
                        self.inventory[allocation["destination_station_id"]][allocation["fuel_type"]]
                        + allocation["quantity"],
                    )
            for allocation in self.allocations:
                if allocation["status"] == "PENDING":
                    allocation["status"] = "IN_TRANSIT"
                    allocation["departure_tick"] = self.tick
            for arrival in self.arrivals:
                if arrival["status"] == "SCHEDULED" and self.tick >= arrival["planned_tick"]:
                    arrival["status"] = "ARRIVED"
                    arrival["actual_tick"] = self.tick
                    self.depots[arrival["depot_id"]][arrival["fuel_type"]] += arrival["quantity"]

    def create_shortage(self, station: str, fuel: str, level: float) -> None:
        self.inventory[station][fuel] = level

    def reset_run(self) -> None:
        self.instance_id += 1
        self.tick = 0
        self.allocations = []
        self.demand_rows = [r for r in self.demand_rows if r["tick"] < 0]
        for station, fuels in self.base.items():
            self.inventory[station] = {f: 9_000.0 for f in fuels}

    # -- HTTP handler ---------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if self.break_reads and path.startswith("/v1/"):
            return httpx.Response(503, json={"detail": "fault injected"})
        if path == "/v1/instance":
            return self._json(
                {
                    "id": self.instance_id,
                    "scenario_id": "baseline",
                    "scenario_version": "1.0.0",
                    "seed": 42,
                    "sim_time": self._sim_time(self.tick).isoformat(),
                    "tick": self.tick,
                    "tick_minutes": TICK_MINUTES,
                    "status": "PAUSED" if self.paused else "RUNNING",
                }
            )
        if path == "/v1/health":
            return self._json(
                {
                    "status": "ok",
                    "database": "ok",
                    "simulation": {"status": "PAUSED" if self.paused else "RUNNING", "tick": self.tick},
                }
            )
        if path == "/v1/regions":
            return self._json(
                [
                    {"id": "region-dhaka", "name": "Dhaka", "demand_factor": 1.0},
                    {"id": "region-chattogram", "name": "Chattogram", "demand_factor": 1.08},
                ]
            )
        if path == "/v1/depots":
            return self._json(
                [
                    {
                        "id": depot_id,
                        "name": depot_id,
                        "region_id": "region-dhaka",
                        "status": "OPEN",
                        "dispatch_capacity_per_tick": 12_000.0,
                        "capacity": {f: 90_000.0 for f in self.depots[depot_id]},
                        "inventory": dict(self.depots[depot_id]),
                    }
                    for depot_id in self.depots
                ]
            )
        if path == "/v1/stations":
            return self._json(
                [
                    {
                        "id": station,
                        "name": station,
                        "region_id": "region-dhaka",
                        "status": "OPEN",
                        "demand_profile": "urban_high",
                        "demand_multiplier": 1.0,
                        "capacity": dict(self.capacity[station]),
                        "inventory": dict(self.inventory[station]),
                    }
                    for station in self.base
                ]
            )
        if path == "/v1/routes":
            return self._json(self.routes)
        if path == "/v1/supply-arrivals":
            return self._json(self.arrivals)
        if path == "/v1/events":
            return self._json(self.events)
        if path == "/v1/allocations" and request.method == "GET":
            return self._json(self.allocations)
        if path == "/v1/allocations" and request.method == "POST":
            body = json_loads(request.content)
            self.post_bodies.append(body)
            if self.fail_next_post:
                # Ambiguous failure: the allocation IS created but the caller
                # never sees the 201 (crash/timeout simulation).
                self.fail_next_post = False
                route = next((r for r in self.routes if r["id"] == body["route_id"]), None)
                self.next_allocation_id += 1
                self.allocations.append({
                    "id": self.next_allocation_id,
                    **body,
                    "created_tick": self.tick,
                    "departure_tick": None,
                    "expected_arrival_tick": self.tick + (route["transit_ticks"] if route else 2),
                    "actual_arrival_tick": None,
                    "status": "PENDING",
                    "failure_reason": None,
                })
                return httpx.Response(500, json={"detail": "boom"})
            for existing in self.allocations:
                if existing["idempotency_key"] == body["idempotency_key"]:
                    if existing["quantity"] != body["quantity"]:
                        return httpx.Response(409, json={"detail": "conflict"})
                    return httpx.Response(201, json=existing)
            # Simulator validation: route must connect; depot stock must cover.
            route = next((r for r in self.routes if r["id"] == body["route_id"]), None)
            if route is None or route["source_depot_id"] != body["source_depot_id"] or route["destination_station_id"] != body["destination_station_id"]:
                return httpx.Response(422, json={"detail": "invalid route"})
            if self.depots[body["source_depot_id"]][body["fuel_type"]] < body["quantity"]:
                return httpx.Response(422, json={"detail": "insufficient depot stock"})
            station_room = (
                self.capacity[body["destination_station_id"]][body["fuel_type"]]
                - self.inventory[body["destination_station_id"]][body["fuel_type"]]
            )
            if station_room < body["quantity"]:
                return httpx.Response(422, json={"detail": "insufficient station capacity"})
            self.next_allocation_id += 1
            allocation = {
                "id": self.next_allocation_id,
                **body,
                "created_tick": self.tick,
                "departure_tick": None,
                "expected_arrival_tick": self.tick + route["transit_ticks"],
                "actual_arrival_tick": None,
                "status": "PENDING",
                "failure_reason": None,
            }
            self.allocations.append(allocation)
            if self.malformed_post_response:
                self.malformed_post_response = False
                return httpx.Response(201, json={"id": allocation["id"]})
            return httpx.Response(201, json=allocation)
        if path == "/v1/demand-history":
            station = request.url.params.get("station_id")
            if station and self.fail_station_history:
                return httpx.Response(503, json={"detail": "history unavailable"})
            limit = int(request.url.params.get("limit", 200))
            rows = [r for r in self.demand_rows if station is None or r["station_id"] == station]
            return self._json(rows[-limit:])
        return httpx.Response(404, json={"detail": "not found"})

    def _json(self, payload: Any) -> httpx.Response:
        response = httpx.Response(200, json=payload)
        if self.stale:
            response.headers["X-Simulator-Stale"] = "true"
        return response


def json_loads(content: bytes) -> dict[str, Any]:
    import json

    return json.loads(content)


def make_policy(tmp_path, **overrides: object) -> PolicyConfig:
    defaults: dict[str, object] = {
        "loop_enabled": False,
        "execution_enabled": True,
        "planning_horizon": 24,
        "immediate_risk_horizon": 6,
        "solver_wall_timeout_seconds": 5.0,
        "bootstrap_demand_limit": 2000,
        "training_min_samples": 200,
    }
    defaults.update(overrides)
    return PolicyConfig(**defaults)  # type: ignore[arg-type]


def make_engine(world: FakeSimulator, policy: PolicyConfig) -> IntelligenceEngine:
    transport = httpx.MockTransport(world.handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://simulator.test")
    # Unit tests use an explicitly write-enabled fake simulator; production
    # defaults to the shared global write gate, which is disabled.
    return IntelligenceEngine(http, policy, simulator_writes_enabled=True)


def run(engine: IntelligenceEngine, **kwargs: Any) -> Any:
    return asyncio.run(engine.run_once(**kwargs))


class TestFullPipeline:
    def test_bootstrap_train_detect_plan(self, tmp_path) -> None:
        world = FakeSimulator()
        engine = make_engine(world, make_policy(tmp_path))

        run(engine, force=True)  # bootstrap + first analysis

        assert engine.model is not None
        assert engine.last_error is None
        prediction = engine.latest.prediction
        detection = engine.latest.detection
        plan = engine.latest.plan
        assert prediction is not None and detection is not None and plan is not None

        # 4 stations x 3 fuels forecast and projected.
        assert len(prediction.forecasts) == 12
        assert len(prediction.projections) == 12
        assert prediction.as_of_tick == world.tick

        # Healthy world with ~9000L stock: nothing critical, plan is NO_ACTION.
        assert prediction.risk_by_station
        assert plan.method in ("NO_ACTION", "GREEDY_CONSTRAINED")
        assert plan.impact is not None
        status = engine.status()
        assert status.engine == "healthy"
        assert status.training.trained
        assert status.training.samples > 0
        assert status.training.message

    def test_shortage_is_detected_and_planned(self, tmp_path) -> None:
        world = FakeSimulator()
        engine = make_engine(world, make_policy(tmp_path))
        run(engine, force=True)

        # Drain mirpur diesel so it burns out within ~4 ticks (demand ~95-140/tick).
        world.create_shortage("station-mirpur", "DIESEL", 350.0)
        results = run(engine, force=True)

        assert results.plan is not None
        mirpur_actions = [
            r
            for r in results.plan.recommendations
            if r.action.destination_station_id == "station-mirpur"
            and r.action.fuel_type is FuelType.DIESEL
        ]
        assert mirpur_actions, "engine must propose a delivery for the drained station"
        action = mirpur_actions[0].action
        assert action.source_depot_id == "depot-gazipur"
        assert action.route_id == "route-gazipur-mirpur"
        assert action.quantity_liters > 0
        assert action.expected_arrival_tick == world.tick + 2
        assert len(action.idempotency_key) <= 150

        # Detection must have flagged the risk.
        finding_types = {f.type for f in results.detection.findings}
        assert any("STOCKOUT" in t.value or "REPLENISH" in t.value for t in finding_types)

        # Impact: plan should reduce expected unmet demand vs doing nothing.
        impact = results.plan.impact
        assert impact is not None and impact.unmet_avoided_liters > 0

        # Independent whole-plan validation passes.
        assert results.plan.warnings == []

    def test_recommendation_respects_simulator_capacity(self, tmp_path) -> None:
        world = FakeSimulator()
        engine = make_engine(world, make_policy(tmp_path))
        run(engine, force=True)
        world.create_shortage("station-mirpur", "DIESEL", 100.0)
        results = run(engine, force=True)
        for rec in results.plan.recommendations:
            action = rec.action
            route = next(r for r in world.routes if r["id"] == action.route_id)
            assert action.quantity_liters <= route["max_shipment"]
            station_room = world.capacity[action.destination_station_id][action.fuel_type.value] - world.inventory[action.destination_station_id][action.fuel_type.value]
            assert action.quantity_liters <= station_room + 1e-6


class TestApprovalAndExecution:
    def test_approve_execute_reconcile_cycle(self, tmp_path) -> None:
        world = FakeSimulator()
        engine = make_engine(world, make_policy(tmp_path))
        run(engine, force=True)
        world.create_shortage("station-mirpur", "DIESEL", 300.0)
        results = run(engine, force=True)
        plan = results.plan
        assert plan is not None and plan.recommendations

        # Execution without approval is refused.
        refused = asyncio.run(engine.execute_plan(plan.plan_id, "operator-1"))
        assert refused.status is PlanStatus.REJECTED
        assert refused.rejection_reason is RejectionReason.PLAN_MISSING

        approved = engine.approve_plan(plan.plan_id, "operator-1")
        assert approved.status is PlanStatus.APPROVED
        assert approved.approved_by == "operator-1"

        executed = asyncio.run(engine.execute_plan(plan.plan_id, "operator-1"))
        assert executed.status is PlanStatus.APPLIED
        assert all(o.status.value == "submitted" for o in executed.outcomes)

        # The simulator actually received well-formed allocations.
        assert len(world.post_bodies) == len(plan.recommendations)
        for body in world.post_bodies:
            assert set(body) == {
                "idempotency_key",
                "source_depot_id",
                "destination_station_id",
                "route_id",
                "fuel_type",
                "quantity",
            }
            assert body["quantity"] > 0
            assert body["fuel_type"] in {"DIESEL", "PETROL", "OCTANE"}
        keys = [b["idempotency_key"] for b in world.post_bodies]
        assert len(keys) == len(set(keys)), "idempotency keys must be unique per action"

        # Re-executing the same plan is a no-op, never a duplicate submission.
        again = asyncio.run(engine.execute_plan(plan.plan_id, "operator-1"))
        assert again.rejection_reason is RejectionReason.ALREADY_EXECUTED
        assert len(world.post_bodies) == len(plan.recommendations)

    def test_ambiguous_outcome_is_reconciled_not_retried(self, tmp_path) -> None:
        world = FakeSimulator()
        engine = make_engine(world, make_policy(tmp_path))
        run(engine, force=True)
        world.create_shortage("station-mirpur", "DIESEL", 300.0)
        plan = run(engine, force=True).plan
        engine.approve_plan(plan.plan_id, "operator-1")

        # POST fails with 500, but the allocation WAS created server-side.
        world.fail_next_post = True
        executed = asyncio.run(engine.execute_plan(plan.plan_id, "operator-1"))
        submitted = [o for o in executed.outcomes if o.status.value == "submitted"]
        assert submitted, "reconciliation via GET /v1/allocations must recover the outcome"
        assert all(o.simulator_allocation_id for o in submitted)

    def test_execution_disabled_by_policy(self, tmp_path) -> None:
        world = FakeSimulator()
        engine = make_engine(world, make_policy(tmp_path, execution_enabled=False))
        run(engine, force=True)
        world.create_shortage("station-mirpur", "DIESEL", 300.0)
        plan = run(engine, force=True).plan
        engine.approve_plan(plan.plan_id, "operator-1")
        result = asyncio.run(engine.execute_plan(plan.plan_id, "operator-1"))
        assert result.status is PlanStatus.REJECTED
        assert result.rejection_reason is RejectionReason.EXECUTION_DISABLED
        assert world.post_bodies == []

    def test_global_write_gate_blocks_engine_execution(self, tmp_path) -> None:
        world = FakeSimulator()
        policy = make_policy(tmp_path, execution_enabled=True)
        transport = httpx.MockTransport(world.handler)
        http = httpx.AsyncClient(transport=transport, base_url="http://simulator.test")
        engine = IntelligenceEngine(http, policy, simulator_writes_enabled=False)
        run(engine, force=True)
        world.create_shortage("station-mirpur", "DIESEL", 300.0)
        plan = run(engine, force=True).plan
        engine.approve_plan(plan.plan_id, "operator-1")

        assert engine.status().execution_enabled is False
        result = asyncio.run(engine.execute_plan(plan.plan_id, "operator-1"))
        assert result.rejection_reason is RejectionReason.EXECUTION_DISABLED
        assert world.post_bodies == []

    def test_bootstrap_degradation_recovers_after_history_api_recovers(self, tmp_path) -> None:
        world = FakeSimulator()
        world.fail_station_history = True
        engine = make_engine(world, make_policy(tmp_path))
        run(engine, force=True)
        assert engine.status().fallback_active is True

        world.fail_station_history = False
        run(engine, force=True)
        assert engine.status().fallback_active is False

    def test_stale_snapshot_suppresses_recommendations(self, tmp_path) -> None:
        world = FakeSimulator()
        engine = make_engine(world, make_policy(tmp_path))
        world.stale = True
        result = run(engine, force=True)
        assert "stale_data" in engine.snapshot.quality_flags
        assert result.plan is not None
        assert result.plan.recommendations == []
        assert any("stale or inconsistent" in warning for warning in result.plan.warnings)

    def test_revalidation_blocks_submission_when_simulator_marks_stale(self, tmp_path) -> None:
        world = FakeSimulator()
        engine = make_engine(world, make_policy(tmp_path))
        run(engine, force=True)
        world.create_shortage("station-mirpur", "DIESEL", 300.0)
        plan = run(engine, force=True).plan
        engine.approve_plan(plan.plan_id, "operator-1")
        world.stale = True

        result = asyncio.run(engine.execute_plan(plan.plan_id, "operator-1"))
        assert result.rejection_reason is RejectionReason.SNAPSHOT_STALE
        assert world.post_bodies == []

    def test_malformed_success_response_is_reconciled(self, tmp_path) -> None:
        world = FakeSimulator()
        engine = make_engine(world, make_policy(tmp_path))
        run(engine, force=True)
        world.create_shortage("station-mirpur", "DIESEL", 300.0)
        plan = run(engine, force=True).plan
        engine.approve_plan(plan.plan_id, "operator-1")
        world.malformed_post_response = True

        result = asyncio.run(engine.execute_plan(plan.plan_id, "operator-1"))
        assert result.status is PlanStatus.APPLIED
        assert all(outcome.simulator_allocation_id for outcome in result.outcomes)
        assert len(world.post_bodies) == len(plan.recommendations)

    def test_plan_expiry(self, tmp_path) -> None:
        policy = make_policy(tmp_path, plan_expiry_seconds=0.0)
        world = FakeSimulator()
        engine = make_engine(world, policy)
        run(engine, force=True)
        world.create_shortage("station-mirpur", "DIESEL", 300.0)
        plan = run(engine, force=True).plan
        import time

        time.sleep(0.01)
        with pytest.raises(ValueError):
            engine.approve_plan(plan.plan_id, "operator-1")
        assert plan.status is PlanStatus.EXPIRED


class TestResilience:
    def test_operator_status_error_does_not_expose_raw_diagnostics(self, tmp_path) -> None:
        engine = make_engine(FakeSimulator(), make_policy(tmp_path))
        engine.last_error = "SIMULATOR_UNAVAILABLE: connection refused at host:8000"
        status = engine.status()
        assert status.last_error == "The simulator is temporarily unavailable."
        assert "SIMULATOR_UNAVAILABLE" not in status.last_error
        assert "8000" not in status.last_error

    def test_run_transition_resets_alerts(self, tmp_path) -> None:
        world = FakeSimulator()
        engine = make_engine(world, make_policy(tmp_path))
        run(engine, force=True)
        world.create_shortage("station-mirpur", "DIESEL", 300.0)
        run(engine, force=True)
        assert engine.alerts

        world.reset_run()
        run(engine, force=True)
        ended = [r for r in engine.alerts.values() if r.state == "run_ended"]
        assert ended, "old-run alerts must close as RUN_ENDED, not silently vanish"
        # A fresh model is trained for the new run id.
        assert engine.model is not None
        assert engine.run_id != "1:baseline:1.0.0:42"

    def test_upstream_failure_degrades_without_crash(self, tmp_path) -> None:
        world = FakeSimulator()
        engine = make_engine(world, make_policy(tmp_path))
        run(engine, force=True)
        before_plan = engine.latest.plan

        world.break_reads = True
        results = run(engine, force=True)
        assert engine.last_error is not None
        # Last good results are retained (cached advisory view), not wiped.
        assert results.plan is before_plan or results.plan is not None

        world.break_reads = False
        run(engine, force=True)
        assert engine.last_error is None

    def test_one_computation_per_tick_unless_forced(self, tmp_path) -> None:
        world = FakeSimulator()
        engine = make_engine(world, make_policy(tmp_path))
        run(engine, force=True)
        count = engine.run_count
        results = run(engine)  # same tick → cached
        assert engine.run_count == count
        assert results is engine.latest

    def test_revalidation_blocks_submission_on_state_change(self, tmp_path) -> None:
        world = FakeSimulator()
        engine = make_engine(world, make_policy(tmp_path))
        run(engine, force=True)
        world.create_shortage("station-mirpur", "DIESEL", 300.0)
        plan = run(engine, force=True).plan
        engine.approve_plan(plan.plan_id, "operator-1")

        # Someone else fills the tank between approval and execution.
        world.inventory["station-mirpur"]["DIESEL"] = 14_000.0
        result = asyncio.run(engine.execute_plan(plan.plan_id, "operator-1"))
        assert result.status is PlanStatus.REJECTED
        assert result.rejection_reason is RejectionReason.SNAPSHOT_STALE
        assert world.post_bodies == []
