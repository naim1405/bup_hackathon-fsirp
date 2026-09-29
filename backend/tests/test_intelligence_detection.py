"""Tests for detection: observed anomalies, state facts, predictive findings."""

from __future__ import annotations

from datetime import datetime, timezone

from app.intelligence.config import PolicyConfig
from app.intelligence.detection import (
    ArrivalHistory,
    DetectionInputs,
    detect_observed,
    detect_predictive,
)
from app.intelligence.forecaster import DemandModel, ForecastOutput
from app.intelligence.models import FindingType, Severity
from app.intelligence.projection import CellState, project_cell
from app.intelligence.snapshot import Snapshot, StationContext, WorldContext
from app.simulator.models import (
    DemandObservation,
    Depot,
    DomainEvent,
    DomainEventType,
    FuelType,
    Region,
    Route,
    SimulatorInstance,
    Station,
    SupplyArrival,
)


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


def make_snapshot(
    *,
    tick: int = 100,
    stations: list[Station] | None = None,
    routes: list[Route] | None = None,
    depots: list[Depot] | None = None,
    arrivals: list[SupplyArrival] | None = None,
    events: list[DomainEvent] | None = None,
) -> Snapshot:
    return Snapshot(
        run_id="1:baseline:1.0.0:42",
        tick=tick,
        fetched_at_epoch=0.0,
        instance=instance(tick),
        health=None,
        regions=[Region(id="region-dhaka", name="Dhaka", demand_factor=1.0)],
        depots=depots
        or [
            Depot(
                id="depot-1",
                name="d",
                region_id="region-dhaka",
                status="OPEN",
                dispatch_capacity_per_tick=12_000.0,
                capacity={f: 1_000.0 for f in FuelType},
                inventory={f: 1_000.0 for f in FuelType},
            )
        ],
        stations=stations
        or [
            Station(
                id="station-a",
                name="a",
                region_id="region-dhaka",
                status="OPEN",
                demand_profile="urban_high",
                demand_multiplier=1.0,
                capacity={f: 10_000.0 for f in FuelType},
                inventory={f: 5_000.0 for f in FuelType},
            )
        ],
        routes=routes
        or [Route(id="route-a", source_depot_id="depot-1", destination_station_id="station-a", transit_ticks=2, max_shipment=7_000.0, status="AVAILABLE")],
        arrivals=arrivals or [],
        events=events or [],
        allocations=[],
    )


def world(snap: Snapshot) -> WorldContext:
    w = WorldContext(tick_minutes=15)
    for s in snap.stations:
        w.stations[s.id] = StationContext(
            station_id=s.id,
            name=s.name,
            region_id=s.region_id,
            profile=s.demand_profile,
            demand_multiplier_base=1.0,
            live_demand_multiplier=s.demand_multiplier,
        )
    return w


def flat_forecast(station: str, fuel: str, level: float = 100.0) -> ForecastOutput:
    return ForecastOutput(
        point=[level] * 24,
        p10=[level * 0.6] * 24,
        p90=[level * 1.4] * 24,
        method="seasonal_naive_ewma",
        confidence="medium",
        history_count=200,
        ewma_level=None,
        seasonal_reference=level,
        trained_used=False,
        trained_samples=0,
        reasons=[],
    )


def make_inputs(
    snap: Snapshot,
    *,
    model: DemandModel | None = None,
    demand_rows: dict | None = None,
    forecasts: dict | None = None,
    projections: dict | None = None,
    arrival_history: ArrivalHistory | None = None,
    stale: bool = False,
) -> DetectionInputs:
    pol = PolicyConfig()
    mdl = model or DemandModel(pol, world(snap))
    forecasts = forecasts or {
        (s.id, f.value): flat_forecast(s.id, f.value) for s in snap.stations for f in FuelType
    }
    projections = projections or {}
    if not projections:
        for s in snap.stations:
            for fuel in FuelType:
                cell = CellState(
                    station_id=s.id,
                    fuel_type=fuel,
                    inventory_liters=s.inventory.get(fuel, 0.0),
                    capacity_liters=s.capacity.get(fuel, 0.0),
                    open_for_service=s.status == "OPEN",
                )
                path = forecasts[(s.id, fuel.value)].point if forecasts else []
                projections[(s.id, fuel)] = project_cell(cell, path, [], 24)
    return DetectionInputs(
        snapshot=snap,
        policy=pol,
        model=mdl,
        demand_rows=demand_rows or {},
        forecasts=forecasts,  # type: ignore[arg-type]
        projections=projections,  # type: ignore[arg-type]
        arrival_history=arrival_history or ArrivalHistory(),
        stale_data=stale,
    )


class TestObservedDetectors:
    def test_current_stockout(self) -> None:
        snap = make_snapshot()
        snap.stations[0].inventory[FuelType.DIESEL] = 0.0
        findings = detect_observed(make_inputs(snap))
        stockouts = [f for f in findings if f.type is FindingType.CURRENT_STOCKOUT]
        assert len(stockouts) == 1
        assert stockouts[0].severity is Severity.CRITICAL
        assert stockouts[0].fuel_type is FuelType.DIESEL

    def test_no_stockout_finding_when_no_demand(self) -> None:
        """Zero inventory but zero forecast demand must NOT alert (spec: never
        claim a stockout without positive demand)."""
        snap = make_snapshot()
        snap.stations[0].inventory[FuelType.DIESEL] = 0.0
        inputs = make_inputs(snap)
        for f in inputs.forecasts.values():
            f.point = [0.0] * 24
        findings = detect_observed(inputs)
        assert not any(f.type is FindingType.CURRENT_STOCKOUT for f in findings)

    def test_station_outage_and_censored_demand(self) -> None:
        snap = make_snapshot()
        snap.stations[0].status = "OUTAGE"
        snap.stations[0].inventory[FuelType.DIESEL] = 0.0
        findings = detect_observed(make_inputs(snap))
        assert any(f.type is FindingType.STATION_OUTAGE for f in findings)
        # Outage censoring: the empty tank must not raise a stockout alert.
        assert not any(f.type is FindingType.CURRENT_STOCKOUT for f in findings)

    def test_route_blocked(self) -> None:
        snap = make_snapshot()
        snap.routes[0].status = "DISRUPTED"
        findings = detect_observed(make_inputs(snap))
        blocked = [f for f in findings if f.type is FindingType.ROUTE_BLOCKED]
        assert blocked and "route-a" in blocked[0].entity_ids

    def test_supply_eta_slippage_and_overdue(self) -> None:
        arrival = SupplyArrival(
            id="arr-1",
            depot_id="depot-1",
            fuel_type=FuelType.DIESEL,
            quantity=5_000.0,
            planned_tick=97,
            actual_tick=None,
            status="SCHEDULED",
        )
        snap = make_snapshot(arrivals=[arrival])
        history = ArrivalHistory(planned_tick={"arr-1": 95}, quantity={"arr-1": 5_000.0})
        findings = detect_observed(make_inputs(snap, arrival_history=history))
        types = {f.type for f in findings}
        assert FindingType.SUPPLY_ETA_SLIPPAGE in types
        assert FindingType.SUPPLY_OVERDUE in types

    def test_supply_shortfall(self) -> None:
        arrival = SupplyArrival(
            id="arr-1",
            depot_id="depot-1",
            fuel_type=FuelType.PETROL,
            quantity=3_000.0,
            planned_tick=105,
            actual_tick=None,
            status="SCHEDULED",
        )
        snap = make_snapshot(arrivals=[arrival])
        history = ArrivalHistory(planned_tick={"arr-1": 105}, quantity={"arr-1": 5_000.0})
        findings = detect_observed(make_inputs(snap, arrival_history=history))
        assert any(f.type is FindingType.SUPPLY_SHORTFALL for f in findings)

    def test_demand_spike_detection(self) -> None:
        snap = make_snapshot(tick=150)
        # 48 ticks of ~100L history, then a 250L observation at the current tick.
        rows = [(150 - 48 + i, 100.0 + (i % 3)) for i in range(48)]
        rows.append((150, 250.0))
        demand_rows = {("station-a", "DIESEL"): rows}
        findings = detect_observed(make_inputs(snap, demand_rows=demand_rows))
        spikes = [f for f in findings if f.type is FindingType.DEMAND_SPIKE]
        assert spikes, "250L vs 100L baseline must alert"
        assert spikes[0].evidence

    def test_demand_noise_does_not_alert(self) -> None:
        snap = make_snapshot(tick=150)
        rows = [(150 - 48 + i, 100.0 + ((i * 7) % 9)) for i in range(48)]
        rows.append((150, 108.0))
        demand_rows = {("station-a", "DIESEL"): rows}
        findings = detect_observed(make_inputs(snap, demand_rows=demand_rows))
        assert not any(f.type is FindingType.DEMAND_SPIKE for f in findings)

    def test_demand_drop_censored_during_outage(self) -> None:
        snap = make_snapshot(tick=150)
        snap.stations[0].status = "OUTAGE"
        rows = [(150 - 48 + i, 100.0) for i in range(48)]
        rows.append((150, 5.0))
        demand_rows = {("station-a", "DIESEL"): rows}
        findings = detect_observed(make_inputs(snap, demand_rows=demand_rows))
        assert not any(f.type is FindingType.DEMAND_DROP for f in findings)

    def test_stale_data_engineering_finding(self) -> None:
        snap = make_snapshot()
        findings = detect_observed(make_inputs(snap, stale=True))
        assert any(f.type is FindingType.DATA_STALE and f.category == "ENGINEERING" for f in findings)


class TestPredictiveDetectors:
    def _projection(self, snap: Snapshot, inventory: float, demand: float):
        cell = CellState(
            station_id="station-a",
            fuel_type=FuelType.DIESEL,
            inventory_liters=inventory,
            capacity_liters=10_000.0,
            open_for_service=True,
        )
        return project_cell(cell, [demand] * 24, [], 24)

    def test_imminent_shortage_is_high(self) -> None:
        snap = make_snapshot()
        projections = {("station-a", FuelType.DIESEL): self._projection(snap, 250.0, 100.0)}
        inputs = make_inputs(snap, projections=projections)
        earliest = {("station-a", FuelType.DIESEL): 2}
        findings = detect_predictive(inputs, earliest)
        immediate = [
            f
            for f in findings
            if f.type is FindingType.PROJECTED_STOCKOUT and f.severity is Severity.HIGH
        ]
        assert immediate
        assert "2 ticks" in immediate[0].title or "3 ticks" in immediate[0].title

    def test_replenishment_too_late(self) -> None:
        snap = make_snapshot()
        projections = {("station-a", FuelType.DIESEL): self._projection(snap, 150.0, 100.0)}
        inputs = make_inputs(snap, projections=projections)
        earliest = {("station-a", FuelType.DIESEL): 4}  # shortage at +2, arrival at +4
        findings = detect_predictive(inputs, earliest)
        assert any(f.type is FindingType.REPLENISHMENT_TOO_LATE for f in findings)

    def test_no_timely_replenishment_when_arrival_unknown(self) -> None:
        snap = make_snapshot()
        projections = {("station-a", FuelType.DIESEL): self._projection(snap, 150.0, 100.0)}
        inputs = make_inputs(snap, projections=projections)
        findings = detect_predictive(inputs, {("station-a", FuelType.DIESEL): None})
        assert any(f.type is FindingType.NO_TIMELY_REPLENISHMENT for f in findings)
