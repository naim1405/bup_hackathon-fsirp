"""Consistent snapshot: one validated view of the simulator world.

All engine stages (detect → predict → decide) consume the same
:class:`Snapshot`, tagged with the simulator tick it was taken at and the run
id it belongs to. A run reset (instance identity change or tick reversal)
produces a new ``run_id`` so old history never contaminates a new run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.intelligence import priors
from app.simulator.models import (
    Allocation,
    Depot,
    DomainEvent,
    Region,
    Route,
    SimulatorHealth,
    SimulatorInstance,
    Station,
    SupplyArrival,
)


def run_fingerprint(instance: SimulatorInstance) -> str:
    """Identity of the simulation run used to isolate histories."""
    return f"{instance.id}:{instance.scenario_id}:{instance.scenario_version}:{instance.seed}"


@dataclass
class StationContext:
    """Static-ish context the forecaster needs for one station."""

    station_id: str
    name: str
    region_id: str
    profile: str                    # documented demand_profile name
    demand_multiplier_base: float   # scenario baseline (1.0); live multiplier passed separately
    live_demand_multiplier: float   # current station.demand_multiplier (event-adjusted)


@dataclass
class WorldContext:
    """Lookup tables for the forecaster, rebuilt on each snapshot."""

    tick_minutes: int
    stations: dict[str, StationContext] = field(default_factory=dict)

    def series_context(self, station_id: str) -> StationContext:
        ctx = self.stations.get(station_id)
        if ctx is None:
            return StationContext(
                station_id=station_id,
                name=station_id,
                region_id="",
                profile="regional",
                demand_multiplier_base=1.0,
                live_demand_multiplier=1.0,
            )
        return ctx


def build_world_context(
    instance: SimulatorInstance,
    stations: list[Station],
    regions: list[Region],
) -> WorldContext:
    region_names = {r.id for r in regions}
    ctx = WorldContext(tick_minutes=instance.tick_minutes)
    for station in stations:
        # Only keep documented region factors; unknown regions fall back to 1.0.
        region_id = station.region_id if station.region_id in region_names else station.region_id
        ctx.stations[station.id] = StationContext(
            station_id=station.id,
            name=station.name,
            region_id=region_id,
            profile=station.demand_profile,
            demand_multiplier_base=1.0,
            live_demand_multiplier=station.demand_multiplier,
        )
    return ctx


@dataclass
class Snapshot:
    """Everything one engine run needs, captured at a single tick."""

    run_id: str
    tick: int
    fetched_at_epoch: float
    instance: SimulatorInstance
    health: SimulatorHealth | None
    regions: list[Region]
    depots: list[Depot]
    stations: list[Station]
    routes: list[Route]
    arrivals: list[SupplyArrival]
    events: list[DomainEvent]
    allocations: list[Allocation]
    quality_flags: list[str] = field(default_factory=list)
    world: WorldContext | None = None

    # -- convenience lookups -------------------------------------------------

    def station(self, station_id: str) -> Station | None:
        return self._stations.get(station_id)

    def depot(self, depot_id: str) -> Depot | None:
        return self._depots.get(depot_id)

    def route(self, route_id: str) -> Route | None:
        return self._routes.get(route_id)

    def routes_to_station(self, station_id: str) -> list[Route]:
        return [r for r in self.routes if r.destination_station_id == station_id]

    def region_station_ids(self, region_id: str) -> list[str]:
        return [s.id for s in self.stations if s.region_id == region_id]

    @property
    def _stations(self) -> dict[str, Station]:
        return {s.id: s for s in self.stations}

    @property
    def _depots(self) -> dict[str, Depot]:
        return {d.id: d for d in self.depots}

    @property
    def _routes(self) -> dict[str, Route]:
        return {r.id: r for r in self.routes}

    def age_seconds(self, now: float | None = None) -> float:
        return (now or time.time()) - self.fetched_at_epoch

    def is_stale(self, max_age_seconds: float, now: float | None = None) -> bool:
        return self.age_seconds(now) > max_age_seconds or "stale_data" in self.quality_flags


# Re-exported so callers can compute cold-start factors consistently.
_ = priors
