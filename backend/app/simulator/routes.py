"""Read-only proxy endpoints for simulator state."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Annotated

import httpx
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import TypeAdapter, ValidationError

from app.simulator.client import SimulatorClient
from app.simulator.models import (
    Allocation,
    DemandObservation,
    Depot,
    DomainEvent,
    FuelType,
    InventoryUpdatedEvent,
    Region,
    Route,
    SimulationTickEvent,
    SimulatorHealth,
    SimulatorInstance,
    SimulatorMetrics,
    SimulatorNoticeEvent,
    Station,
    StreamProtocolError,
    SupplyArrival,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/simulator", tags=["simulator"])


async def get_simulator_client(request: Request) -> SimulatorClient:
    return request.app.state.simulator_client


async def _fetch(
    client: SimulatorClient,
    path: str,
    response: Response,
    response_type: Any,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    return await client.get_validated(path, TypeAdapter(response_type), response, params=params)


@router.get("/health", response_model=SimulatorHealth, summary="Get simulator health")
async def simulator_health(
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> SimulatorHealth:
    return await _fetch(client, "/v1/health", response, SimulatorHealth)


@router.get("/instance", response_model=SimulatorInstance, summary="Get simulation instance")
async def simulator_instance(
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> SimulatorInstance:
    return await _fetch(client, "/v1/instance", response, SimulatorInstance)


@router.get("/regions", response_model=list[Region], summary="List regions")
async def simulator_regions(
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> list[Region]:
    return await _fetch(client, "/v1/regions", response, list[Region])


@router.get("/depots", response_model=list[Depot], summary="List depots")
async def simulator_depots(
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> list[Depot]:
    return await _fetch(client, "/v1/depots", response, list[Depot])


@router.get("/depots/{entity_id}", response_model=Depot, summary="Get a depot")
async def simulator_depot(
    entity_id: Annotated[str, Path(min_length=1, max_length=120)],
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> Depot:
    return await _fetch(client, f"/v1/depots/{entity_id}", response, Depot)


@router.get("/stations", response_model=list[Station], summary="List stations")
async def simulator_stations(
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> list[Station]:
    return await _fetch(client, "/v1/stations", response, list[Station])


@router.get("/stations/{entity_id}", response_model=Station, summary="Get a station")
async def simulator_station(
    entity_id: Annotated[str, Path(min_length=1, max_length=120)],
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> Station:
    return await _fetch(client, f"/v1/stations/{entity_id}", response, Station)


@router.get("/routes", response_model=list[Route], summary="List routes")
async def simulator_routes(
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> list[Route]:
    return await _fetch(client, "/v1/routes", response, list[Route])


@router.get("/supply-arrivals", response_model=list[SupplyArrival], summary="List supply arrivals")
async def simulator_supply_arrivals(
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> list[SupplyArrival]:
    return await _fetch(client, "/v1/supply-arrivals", response, list[SupplyArrival])


@router.get("/events", response_model=list[DomainEvent], summary="List simulator events")
async def simulator_events(
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> list[DomainEvent]:
    return await _fetch(client, "/v1/events", response, list[DomainEvent])


@router.get("/allocations", response_model=list[Allocation], summary="List allocations")
async def simulator_allocations(
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> list[Allocation]:
    return await _fetch(client, "/v1/allocations", response, list[Allocation])


@router.get("/demand-history", response_model=list[DemandObservation], summary="Get demand history")
async def simulator_demand_history(
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
    station_id: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> list[DemandObservation]:
    params: dict[str, Any] = {"limit": limit}
    if station_id is not None:
        params["station_id"] = station_id
    return await _fetch(
        client,
        "/v1/demand-history",
        response,
        list[DemandObservation],
        params=params,
    )


@router.get("/metrics", response_model=SimulatorMetrics, summary="Get simulator metrics")
async def simulator_metrics(
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> SimulatorMetrics:
    return await _fetch(client, "/v1/metrics", response, SimulatorMetrics)


_EVENT_ADAPTERS = {
    "simulation.tick": TypeAdapter(SimulationTickEvent),
    "allocation.status_changed": TypeAdapter(Allocation),
    "inventory.updated": TypeAdapter(InventoryUpdatedEvent),
    "simulator.notice": TypeAdapter(SimulatorNoticeEvent),
}


async def _validated_sse_body(upstream: httpx.Response) -> AsyncIterator[bytes]:
    """Relay SSE frames, validating all documented event data payloads."""
    event_name = "message"
    data_lines: list[str] = []
    other_fields: list[str] = []

    async for line in upstream.aiter_lines():
        if line == "":
            if data_lines:
                data = "\n".join(data_lines)
                adapter = _EVENT_ADAPTERS.get(event_name)
                if adapter is not None:
                    try:
                        adapter.validate_python(json.loads(data))
                    except (json.JSONDecodeError, ValidationError) as exc:
                        logger.warning("Dropping invalid simulator SSE event %s: %s", event_name, exc)
                        problem = StreamProtocolError(
                            event=event_name,
                            message="The simulator sent an event with an invalid payload.",
                        ).model_dump_json()
                        yield f"event: simulator.protocol_error\ndata: {problem}\n\n".encode()
                        event_name, data_lines, other_fields = "message", [], []
                        continue
                if event_name != "message":
                    yield f"event: {event_name}\n".encode()
                for field in other_fields:
                    yield f"{field}\n".encode()
                for data_line in data_lines:
                    yield f"data: {data_line}\n".encode()
                yield b"\n"
            event_name, data_lines, other_fields = "message", [], []
            continue

        if line.startswith(":"):
            # Keepalive comments (including : connected and : keepalive) are
            # part of SSE's liveness protocol and are passed through verbatim.
            yield f"{line}\n".encode()
        elif line.startswith("event:"):
            event_name = line.partition(":")[2].strip() or "message"
        elif line.startswith("data:"):
            value = line.partition(":")[2]
            data_lines.append(value[1:] if value.startswith(" ") else value)
        elif line.startswith("id:") or line.startswith("retry:"):
            other_fields.append(line)
        else:
            # Ignore malformed/unsupported fields rather than forwarding them.
            logger.debug("Ignoring unsupported SSE line from simulator")


@router.get("/stream", summary="Subscribe to simulator event stream")
async def simulator_stream(
    request: Request,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> StreamingResponse:
    """Proxy validated simulator SSE notifications to the caller."""
    upstream = await client.open_event_stream()

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in _validated_sse_body(upstream):
                if await request.is_disconnected():
                    break
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
