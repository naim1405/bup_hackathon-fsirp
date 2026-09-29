"""A tiny deterministic fake of the BUP Fuel Supply Simulator.

Purpose: local development and demos when the organizer's simulator image is
not available. It implements the documented public read API, allocation
submission/cancellation, and a few admin controls. It is a TEST DOUBLE — the
real simulator image remains the source of truth for judging.

Run from backend/:
    uvicorn tools.fake_simulator:app --port 8000

Environment:
    FAKE_SPEED_TICKS_PER_SECOND (default 1.0, 0 = paused)
    FAKE_START_TICK (default 0), FAKE_HISTORY_TICKS (default 400)
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import Body, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

TICK_MINUTES = 15
START_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)

STATIONS = {
    "station-mirpur": {"DIESEL": 95.0, "PETROL": 110.0, "OCTANE": 55.0},
    "station-tongi": {"DIESEL": 140.0, "PETROL": 45.0, "OCTANE": 22.0},
    "station-karnaphuli": {"DIESEL": 85.0, "PETROL": 90.0, "OCTANE": 48.0},
    "station-coxsbazar": {"DIESEL": 70.0, "PETROL": 72.0, "OCTANE": 35.0},
}
STATION_CAPACITY = {
    "station-mirpur": {"DIESEL": 15_000.0, "PETROL": 14_000.0, "OCTANE": 9_000.0},
    "station-tongi": {"DIESEL": 18_000.0, "PETROL": 9_000.0, "OCTANE": 6_000.0},
    "station-karnaphuli": {"DIESEL": 14_000.0, "PETROL": 15_000.0, "OCTANE": 9_000.0},
    "station-coxsbazar": {"DIESEL": 12_000.0, "PETROL": 12_000.0, "OCTANE": 7_000.0},
}
STATION_PROFILES = {
    "station-mirpur": "urban_high",
    "station-tongi": "industrial",
    "station-karnaphuli": "highway",
    "station-coxsbazar": "regional",
}
DEPOTS = {
    "depot-gazipur": {"DIESEL": 60_000.0, "PETROL": 45_000.0, "OCTANE": 26_000.0},
    "depot-patiya": {"DIESEL": 55_000.0, "PETROL": 42_000.0, "OCTANE": 24_000.0},
}
DEPOT_CAPACITY = {
    "depot-gazipur": {"DIESEL": 90_000.0, "PETROL": 70_000.0, "OCTANE": 45_000.0},
    "depot-patiya": {"DIESEL": 85_000.0, "PETROL": 65_000.0, "OCTANE": 40_000.0},
}
ROUTES = [
    {"id": "route-gazipur-mirpur", "source_depot_id": "depot-gazipur", "destination_station_id": "station-mirpur", "transit_ticks": 2, "max_shipment": 7000.0, "status": "AVAILABLE"},
    {"id": "route-gazipur-tongi", "source_depot_id": "depot-gazipur", "destination_station_id": "station-tongi", "transit_ticks": 2, "max_shipment": 6500.0, "status": "AVAILABLE"},
    {"id": "route-patiya-karnaphuli", "source_depot_id": "depot-patiya", "destination_station_id": "station-karnaphuli", "transit_ticks": 2, "max_shipment": 7000.0, "status": "AVAILABLE"},
    {"id": "route-patiya-coxsbazar", "source_depot_id": "depot-patiya", "destination_station_id": "station-coxsbazar", "transit_ticks": 3, "max_shipment": 6000.0, "status": "AVAILABLE"},
    {"id": "route-gazipur-karnaphuli", "source_depot_id": "depot-gazipur", "destination_station_id": "station-karnaphuli", "transit_ticks": 4, "max_shipment": 5000.0, "status": "AVAILABLE"},
    {"id": "route-patiya-mirpur", "source_depot_id": "depot-patiya", "destination_station_id": "station-mirpur", "transit_ticks": 4, "max_shipment": 5000.0, "status": "AVAILABLE"},
]
INITIAL_ARRIVALS = [
    {"id": "arr-1", "depot_id": "depot-gazipur", "fuel_type": "DIESEL", "quantity": 30_000.0, "planned_tick": 12, "actual_tick": None, "status": "SCHEDULED"},
    {"id": "arr-2", "depot_id": "depot-patiya", "fuel_type": "PETROL", "quantity": 22_000.0, "planned_tick": 76, "actual_tick": None, "status": "SCHEDULED"},
]


def demand_at(tick: int, base: float) -> float:
    tod = tick % 96
    factor = 1.5 if 24 <= tod < 72 else 0.6
    noise = ((tick * 37) % 11 - 5) / 100.0
    return max(1.0, base * factor * (1.0 + noise))


class World:
    def __init__(self) -> None:
        self.instance_id = 1
        self.tick = int(os.getenv("FAKE_START_TICK", "0"))
        self.running = os.getenv("FAKE_SPEED_TICKS_PER_SECOND", "1") != "0"
        self.speed = max(0.05, float(os.getenv("FAKE_SPEED_TICKS_PER_SECOND", "1")))
        self.inventory = {s: {f: 9_000.0 for f in fuels} for s, fuels in STATIONS.items()}
        self.depot_inventory = {d: dict(fuels) for d, fuels in DEPOTS.items()}
        self.routes = [dict(r) for r in ROUTES]
        self.arrivals = [dict(a) for a in INITIAL_ARRIVALS]
        self.events: list[dict] = []
        self.allocations: list[dict] = []
        self.demand_rows: list[dict] = []
        self._next_row_id = 1
        self._next_allocation_id = 1000
        for tick in range(max(0, self.tick - int(os.getenv("FAKE_HISTORY_TICKS", "400"))), self.tick + 1):
            self._record_demand(tick, serve=False)

    # -- internals -----------------------------------------------------------

    def _sim_time(self, tick: int) -> str:
        return (START_EPOCH + timedelta(minutes=tick * TICK_MINUTES)).isoformat()

    def _record_demand(self, tick: int, serve: bool = True) -> None:
        for station, fuels in STATIONS.items():
            for fuel, base in fuels.items():
                want = demand_at(tick, base)
                served = want
                if serve:
                    served = min(want, self.inventory[station][fuel])
                    self.inventory[station][fuel] -= served
                self.demand_rows.append(
                    {
                        "id": self._next_row_id,
                        "station_id": station,
                        "fuel_type": fuel,
                        "tick": tick,
                        "sim_time": self._sim_time(tick),
                        "demand_liters": want,
                        "served_liters": served,
                        "unmet_liters": want - served,
                    }
                )
                self._next_row_id += 1

    def step(self, ticks: int = 1) -> None:
        for _ in range(ticks):
            self.tick += 1
            self._record_demand(self.tick)
            for allocation in self.allocations:
                if allocation["status"] == "PENDING":
                    allocation["status"] = "IN_TRANSIT"
                    allocation["departure_tick"] = self.tick
                elif (
                    allocation["status"] == "IN_TRANSIT"
                    and allocation["expected_arrival_tick"] is not None
                    and self.tick >= allocation["expected_arrival_tick"]
                ):
                    allocation["status"] = "ARRIVED"
                    allocation["actual_arrival_tick"] = self.tick
                    station = allocation["destination_station_id"]
                    fuel = allocation["fuel_type"]
                    room = STATION_CAPACITY[station][fuel] - self.inventory[station][fuel]
                    self.inventory[station][fuel] += min(room, allocation["quantity"])
            for arrival in self.arrivals:
                if arrival["status"] in ("SCHEDULED", "DELAYED") and self.tick >= arrival["planned_tick"]:
                    arrival["status"] = "ARRIVED"
                    arrival["actual_tick"] = self.tick
                    self.depot_inventory[arrival["depot_id"]][arrival["fuel_type"]] += arrival["quantity"]
            for event in self.events:
                if event["status"] == "SCHEDULED" and self.tick >= event["start_tick"]:
                    event["status"] = "ACTIVE"
                elif event["status"] == "ACTIVE" and self.tick >= event["end_tick"]:
                    event["status"] = "RESOLVED"
                    for route in self.routes:
                        if route["id"] in event.get("_affected_routes", []):
                            route["status"] = "AVAILABLE"

    # -- snapshots ------------------------------------------------------------

    def instance(self) -> dict:
        return {
            "id": self.instance_id,
            "scenario_id": "baseline",
            "scenario_version": "1.0.0",
            "seed": 42,
            "sim_time": self._sim_time(self.tick),
            "tick": self.tick,
            "tick_minutes": TICK_MINUTES,
            "status": "RUNNING" if self.running else "PAUSED",
        }

    def depots(self) -> list[dict]:
        return [
            {
                "id": depot_id,
                "name": depot_id,
                "region_id": "region-dhaka" if depot_id == "depot-gazipur" else "region-chattogram",
                "status": "OPEN",
                "dispatch_capacity_per_tick": 12_000.0,
                "capacity": dict(DEPOT_CAPACITY[depot_id]),
                "inventory": dict(self.depot_inventory[depot_id]),
            }
            for depot_id in self.depot_inventory
        ]

    def stations(self) -> list[dict]:
        return [
            {
                "id": station,
                "name": station,
                "region_id": "region-dhaka",
                "status": "OPEN",
                "demand_profile": STATION_PROFILES[station],
                "demand_multiplier": 1.0,
                "capacity": dict(STATION_CAPACITY[station]),
                "inventory": dict(self.inventory[station]),
            }
            for station in self.inventory
        ]


world = World()
app = FastAPI(title="Fake BUP Fuel Supply Simulator", version="fake-1.0.0")


@app.get("/v1/health")
def health() -> dict:
    return {"status": "ok", "database": "ok", "simulation": {"status": "RUNNING" if world.running else "PAUSED", "tick": world.tick}}


@app.get("/v1/instance")
def instance() -> dict:
    return world.instance()


@app.get("/v1/regions")
def regions() -> list[dict]:
    return [
        {"id": "region-dhaka", "name": "Dhaka Division", "demand_factor": 1.0},
        {"id": "region-chattogram", "name": "Chattogram Division", "demand_factor": 1.08},
    ]


@app.get("/v1/depots")
def depots() -> list[dict]:
    return world.depots()


@app.get("/v1/depots/{entity_id}")
def depot_detail(entity_id: str) -> dict:
    for depot in world.depots():
        if depot["id"] == entity_id:
            return depot
    raise HTTPException(404, "depot not found")


@app.get("/v1/stations")
def stations() -> list[dict]:
    return world.stations()


@app.get("/v1/stations/{entity_id}")
def station_detail(entity_id: str) -> dict:
    for station in world.stations():
        if station["id"] == entity_id:
            return station
    raise HTTPException(404, "station not found")


@app.get("/v1/routes")
def routes() -> list[dict]:
    return world.routes


@app.get("/v1/supply-arrivals")
def supply_arrivals() -> list[dict]:
    return world.arrivals


@app.get("/v1/events")
def events() -> list[dict]:
    return [
        {k: v for k, v in event.items() if not k.startswith("_")}
        for event in world.events
    ]


@app.get("/v1/allocations")
def allocations() -> list[dict]:
    return world.allocations


@app.get("/v1/demand-history")
def demand_history(station_id: str | None = None, limit: int = 200) -> list[dict]:
    rows = [r for r in world.demand_rows if station_id is None or r["station_id"] == station_id]
    return rows[-max(1, min(limit, 2000)):]


@app.get("/v1/metrics")
def metrics() -> dict:
    served = sum(r["served_liters"] for r in world.demand_rows)
    unmet = sum(r["unmet_liters"] for r in world.demand_rows)
    return {
        "served_demand_liters": served,
        "unmet_demand_liters": unmet,
        "service_level": served / (served + unmet) if served + unmet else 1.0,
        "allocation_liters": sum(a["quantity"] for a in world.allocations if a["status"] in ("IN_TRANSIT", "ARRIVED")),
        "allocation_failures": sum(1 for a in world.allocations if a["status"] == "FAILED"),
    }


@app.post("/v1/allocations", status_code=201)
async def create_allocation(request: Request) -> dict:
    body = await request.json()
    for field in ("idempotency_key", "source_depot_id", "destination_station_id", "route_id", "fuel_type", "quantity"):
        if field not in body:
            raise HTTPException(422, f"missing {field}")
    if body["fuel_type"] not in ("DIESEL", "PETROL", "OCTANE") or body["quantity"] <= 0:
        raise HTTPException(422, "invalid fuel or quantity")
    for existing in world.allocations:
        if existing["idempotency_key"] == body["idempotency_key"]:
            if existing["quantity"] != body["quantity"]:
                raise HTTPException(409, "idempotency key conflict")
            return existing
    route = next((r for r in world.routes if r["id"] == body["route_id"]), None)
    if route is None or route["source_depot_id"] != body["source_depot_id"] or route["destination_station_id"] != body["destination_station_id"]:
        raise HTTPException(422, "route does not connect source and destination")
    if route["status"] != "AVAILABLE":
        raise HTTPException(422, "route is disrupted")
    if route["max_shipment"] < body["quantity"]:
        raise HTTPException(422, "quantity exceeds route max shipment")
    if world.depot_inventory[body["source_depot_id"]][body["fuel_type"]] < body["quantity"]:
        raise HTTPException(422, "insufficient depot inventory")
    station = body["destination_station_id"]
    fuel = body["fuel_type"]
    if STATION_CAPACITY[station][fuel] - world.inventory[station][fuel] < body["quantity"]:
        raise HTTPException(422, "insufficient station capacity")
    world._next_allocation_id += 1
    allocation = {
        "id": world._next_allocation_id,
        **body,
        "created_tick": world.tick,
        "departure_tick": None,
        "expected_arrival_tick": world.tick + route["transit_ticks"],
        "actual_arrival_tick": None,
        "status": "PENDING",
        "failure_reason": None,
    }
    world.allocations.append(allocation)
    world.depot_inventory[body["source_depot_id"]][fuel] -= body["quantity"]
    return allocation


@app.post("/v1/allocations/{allocation_id}/cancel")
def cancel_allocation(allocation_id: int) -> dict:
    for allocation in world.allocations:
        if allocation["id"] == allocation_id:
            if allocation["status"] != "PENDING":
                raise HTTPException(409, "only PENDING allocations can be cancelled")
            allocation["status"] = "CANCELLED"
            world.depot_inventory[allocation["source_depot_id"]][allocation["fuel_type"]] += allocation["quantity"]
            return {"id": allocation_id, "status": "CANCELLED"}
    raise HTTPException(404, "allocation not found")


# -- minimal admin controls (demo/testing only) --------------------------------


class EventCreate(BaseModel):
    type: str
    start_tick: int = Field(ge=0)
    duration_ticks: int = Field(gt=0)
    parameters: dict = Field(default_factory=dict)


@app.post("/admin/step")
def admin_step(body: dict = Body(default={})) -> dict:
    world.step(int(body.get("ticks", 1)))
    return world.instance()


@app.post("/admin/toggle")
def admin_toggle() -> dict:
    world.running = not world.running
    return world.instance()


@app.post("/admin/events")
def admin_event(event: EventCreate, status_code: int = 201) -> dict:
    record = event.model_dump()
    record.update({"id": len(world.events) + 1, "status": "SCHEDULED", "_ts": time.time()})
    if event.type == "route_disruption":
        target = event.parameters.get("route_id", "route-gazipur-mirpur")
        record["_affected_routes"] = [target]
        for route in world.routes:
            if route["id"] == target:
                route["status"] = "DISRUPTED"
    world.events.append(record)
    return {k: v for k, v in record.items() if not k.startswith("_")}


@app.post("/admin/demo/shortage")
def admin_shortage(body: dict = Body(...)) -> dict:
    """Demo helper: drain a station tank to trigger the intelligence loop."""
    station = body["station_id"]
    fuel = body["fuel_type"]
    level = float(body.get("level", 300.0))
    if station not in world.inventory or fuel not in world.inventory[station]:
        raise HTTPException(404, "unknown station/fuel")
    world.inventory[station][fuel] = level
    return {"station_id": station, "fuel_type": fuel, "inventory": level}


@app.post("/admin/demo/route_disruption")
def admin_route_disruption(body: dict = Body(default={})) -> dict:
    route_id = body.get("route_id", "route-gazipur-mirpur")
    for route in world.routes:
        if route["id"] == route_id:
            route["status"] = "DISRUPTED"
            return {"route_id": route_id, "status": "DISRUPTED"}
    raise HTTPException(404, "unknown route")


@app.get("/admin/state")
def admin_state() -> dict:
    return {
        "tick": world.tick,
        "instance": world.instance(),
        "inventory": world.inventory,
        "depot_inventory": world.depot_inventory,
        "allocations": len(world.allocations),
    }


# -- background ticker ---------------------------------------------------------


async def _ticker() -> None:
    interval = 1.0 / world.speed
    while True:
        await asyncio.sleep(interval)
        if world.running:
            world.step(1)


@app.on_event("startup")
async def _start() -> None:
    threading.Timer(0.0, lambda: None).cancel()
    app.state.ticker = asyncio.create_task(_ticker())
