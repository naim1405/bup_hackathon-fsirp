"""Frontend-oriented, best-effort dashboard snapshot endpoint."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, TypeAdapter

from app.simulator.client import SimulatorClient, ValidatedSimulatorResult
from app.simulator.models import (
    Allocation,
    DemandObservation,
    Depot,
    DomainEvent,
    Region,
    Route,
    SimulatorHealth,
    SimulatorInstance,
    SimulatorMetrics,
    Station,
    SupplyArrival,
)
from app.simulator.routes import get_simulator_client

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


class ResourceStatus(BaseModel):
    status: Literal["available", "stale", "unavailable"]
    error_code: str | None = None
    message: str | None = None
    upstream_status: int | None = None


class DashboardSnapshot(BaseModel):
    requested_at: datetime
    as_of_tick: int | None
    consistent: bool
    complete: bool
    stale: bool
    simulator_health: SimulatorHealth | None
    instance: SimulatorInstance | None
    regions: list[Region] | None
    depots: list[Depot] | None
    stations: list[Station] | None
    routes: list[Route] | None
    supply_arrivals: list[SupplyArrival] | None
    events: list[DomainEvent] | None
    allocations: list[Allocation] | None
    demand_history: list[DemandObservation] | None
    metrics: SimulatorMetrics | None
    resource_status: dict[str, ResourceStatus]


@dataclass(frozen=True)
class _FetchOutcome:
    data: Any | None
    status: ResourceStatus


async def _fetch_resource(
    client: SimulatorClient,
    name: str,
    path: str,
    response_type: Any,
    *,
    params: dict[str, Any] | None = None,
) -> _FetchOutcome:
    try:
        result: ValidatedSimulatorResult = await client.get_validated_result(
            path, TypeAdapter(response_type), params=params
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        upstream_status = detail.get("upstream_status")
        return _FetchOutcome(
            data=None,
            status=ResourceStatus(
                status="unavailable",
                error_code=detail.get("upstream_code") or detail.get("code", "SIMULATOR_REQUEST_FAILED"),
                message=detail.get("message")
                or f"Could not fetch {name} from the simulator (HTTP {exc.status_code}).",
                upstream_status=upstream_status if isinstance(upstream_status, int) else None,
            ),
        )
    return _FetchOutcome(
        data=result.data,
        status=ResourceStatus(status="stale" if result.stale else "available"),
    )


@router.get(
    "/snapshot",
    response_model=DashboardSnapshot,
    summary="Get a validated, best-effort dashboard snapshot",
    description=(
        "Fetches dashboard resources in parallel through the backend. Partial results are "
        "returned with per-resource status so the frontend can render available state and "
        "surface simulator failures. This is not a simulator-side transaction."
    ),
)
async def dashboard_snapshot(
    response: Response,
    client: SimulatorClient = Depends(get_simulator_client),
    history_limit: int = Query(default=200, ge=1, le=2000),
    station_id: str | None = Query(default=None, min_length=1, max_length=120),
) -> DashboardSnapshot:
    """Fetch a UI-friendly aggregate without duplicating simulator-owned state."""
    before = await _fetch_resource(client, "instance", "/v1/instance", SimulatorInstance)
    history_params: dict[str, Any] = {"limit": history_limit}
    if station_id is not None:
        history_params["station_id"] = station_id

    resources: dict[str, tuple[str, Any, dict[str, Any] | None]] = {
        "simulator_health": ("/v1/health", SimulatorHealth, None),
        "regions": ("/v1/regions", list[Region], None),
        "depots": ("/v1/depots", list[Depot], None),
        "stations": ("/v1/stations", list[Station], None),
        "routes": ("/v1/routes", list[Route], None),
        "supply_arrivals": ("/v1/supply-arrivals", list[SupplyArrival], None),
        "events": ("/v1/events", list[DomainEvent], None),
        "allocations": ("/v1/allocations", list[Allocation], None),
        "demand_history": ("/v1/demand-history", list[DemandObservation], history_params),
        "metrics": ("/v1/metrics", SimulatorMetrics, None),
    }

    names = list(resources)
    outcomes = await asyncio.gather(
        *(
            _fetch_resource(client, name, path, response_type, params=params)
            for name, (path, response_type, params) in resources.items()
        )
    )
    collected = dict(zip(names, outcomes, strict=True))
    after = await _fetch_resource(client, "instance", "/v1/instance", SimulatorInstance)

    instance_outcome = after if after.data is not None else before
    collected["instance"] = instance_outcome
    statuses = {name: outcome.status for name, outcome in collected.items()}

    before_tick = before.data.tick if before.data is not None else None
    after_tick = after.data.tick if after.data is not None else None
    consistent = before_tick is not None and after_tick is not None and before_tick == after_tick
    unavailable = any(status.status == "unavailable" for status in statuses.values())
    stale = any(status.status == "stale" for status in statuses.values())
    if stale:
        response.headers["X-Simulator-Stale"] = "true"

    payload = {name: outcome.data for name, outcome in collected.items()}
    return DashboardSnapshot(
        requested_at=datetime.now(timezone.utc),
        as_of_tick=after_tick if after_tick is not None else before_tick,
        consistent=consistent,
        complete=not unavailable,
        stale=stale,
        resource_status=statuses,
        **payload,
    )
