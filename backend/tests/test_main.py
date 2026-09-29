from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import pytest

from app import operations
from app.main import app
from app.simulator.client import SimulatorClient
from app.simulator.routes import _validated_sse_body, get_simulator_client


Handler = Callable[[httpx.Request], httpx.Response]


class APIClient:
    """Synchronous test helper backed by HTTPX's in-process ASGI transport."""

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        async def request() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                return await client.get(path, **kwargs)

        return asyncio.run(request())

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        async def request() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                return await client.post(path, **kwargs)

        return asyncio.run(request())


@pytest.fixture
def api_client(request):
    time_suffix = getattr(request, "param", "+00:00")
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/v1/allocations":
            body = json.loads(request.content)
            return httpx.Response(
                201,
                json={
                    "id": 11,
                    **body,
                    "route_id": "route-dhaka-mirpur",
                    "created_tick": 3,
                    "status": "PENDING",
                },
            )
        if request.method == "POST" and path == "/v1/allocations/11/cancel":
            return httpx.Response(
                200,
                json={
                    "id": 11,
                    "idempotency_key": "op-test-11",
                    "source_depot_id": "depot-gazipur",
                    "destination_station_id": "station-mirpur",
                    "route_id": "route-dhaka-mirpur",
                    "fuel_type": "DIESEL",
                    "quantity": 500,
                    "created_tick": 3,
                    "status": "CANCELLED",
                },
            )
        if path == "/v1/instance":
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "scenario_id": "baseline",
                    "scenario_version": "1.0",
                    "seed": 12345,
                    "sim_time": f"2026-01-01T00:00:00{time_suffix}",
                    "tick": 0,
                    "tick_minutes": 15,
                    "status": "PAUSED",
                },
            )
        if path == "/v1/health":
            return httpx.Response(
                200,
                json={"status": "ok", "database": "ok", "simulation": {"status": "PAUSED", "tick": 0}},
            )
        if path in {"/v1/regions", "/v1/depots", "/v1/supply-arrivals", "/v1/events"}:
            return httpx.Response(200, json=[])
        if path == "/v1/allocations":
            return httpx.Response(200, json=[])
        if path == "/v1/stations":
            return httpx.Response(
                200,
                headers={"X-Simulator-Stale": "true"},
                json=[
                    {
                        "id": "station-mirpur",
                        "name": "Mirpur Fuel Station",
                        "region_id": "region-dhaka",
                        "status": "OPEN",
                        "demand_profile": "urban_high",
                        "demand_multiplier": 1.0,
                        "capacity": {"DIESEL": 15000, "PETROL": 14000, "OCTANE": 9000},
                        "inventory": {"DIESEL": 9000, "PETROL": 9000, "OCTANE": 5000},
                    }
                ],
            )
        if path == "/v1/demand-history":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 4,
                        "station_id": "station-mirpur",
                        "fuel_type": "DIESEL",
                        "tick": 3,
                        "sim_time": f"2026-01-01T00:45:00{time_suffix}",
                        "demand_liters": 95.1,
                        "served_liters": 90.0,
                        "unmet_liters": 5.1,
                    }
                ],
            )
        if path == "/v1/routes":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "route-dhaka-mirpur",
                        "source_depot_id": "depot-gazipur",
                        "destination_station_id": "station-mirpur",
                        "transit_ticks": 2,
                        "max_shipment": 2000,
                        "status": "AVAILABLE",
                    }
                ],
            )
        if path == "/v1/metrics":
            return httpx.Response(
                200,
                json={
                    "served_demand_liters": 90,
                    "unmet_demand_liters": 5,
                    "service_level": 1.4,
                    "allocation_liters": 500,
                    "allocation_failures": 0,
                },
            )
        return httpx.Response(404, json={"detail": {"code": "NOT_FOUND"}})

    async def mock_simulator_dependency():
        async with httpx.AsyncClient(
            base_url="http://simulator.test",
            transport=httpx.MockTransport(handler),
        ) as upstream_http:
            yield SimulatorClient(upstream_http)

    app.dependency_overrides[get_simulator_client] = mock_simulator_dependency
    try:
        yield APIClient(), calls
    finally:
        app.dependency_overrides.clear()


def test_root_returns_service_information(api_client) -> None:
    client, _ = api_client
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "fsirp-backend"
    assert body["status"] == "ok"
    assert body["simulator_api"] == "/api/v1/simulator"


def test_backend_health_is_independent_of_simulator(api_client) -> None:
    client, calls = api_client
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "fsirp-backend"}
    assert calls == []


@pytest.mark.parametrize("api_client", ["", "+00:00", "+06:00"], indirect=True)
def test_simulator_instance_is_fetched_and_validated(api_client, request) -> None:
    client, calls = api_client
    response = client.get("/api/v1/simulator/instance")

    assert response.status_code == 200
    assert response.json()["scenario_id"] == "baseline"
    assert calls[-1].url.path == "/v1/instance"
    assert datetime.fromisoformat(response.json()["sim_time"]) == datetime.fromisoformat(
        f"2026-01-01T00:00:00{request.node.callspec.params['api_client']}"
    )


def test_simulator_data_and_stale_header_are_forwarded(api_client) -> None:
    client, _ = api_client
    response = client.get("/api/v1/simulator/stations")

    assert response.status_code == 200
    assert response.json()[0]["id"] == "station-mirpur"
    assert response.headers["X-Simulator-Stale"] == "true"


@pytest.mark.parametrize("api_client", ["", "+00:00", "+06:00"], indirect=True)
def test_demand_history_query_is_validated_and_forwarded(api_client, request) -> None:
    client, calls = api_client
    response = client.get(
        "/api/v1/simulator/demand-history",
        params={"station_id": "station-mirpur", "limit": 100},
    )

    assert response.status_code == 200
    assert response.json()[0]["unmet_liters"] == 5.1
    assert datetime.fromisoformat(response.json()[0]["sim_time"]) == datetime.fromisoformat(
        f"2026-01-01T00:45:00{request.node.callspec.params['api_client']}"
    )
    assert calls[-1].url.params["station_id"] == "station-mirpur"
    assert calls[-1].url.params["limit"] == "100"


def test_demand_history_rejects_out_of_range_limit_without_upstream_call(api_client) -> None:
    client, calls = api_client
    before = len(calls)

    response = client.get("/api/v1/simulator/demand-history?limit=2001")

    assert response.status_code == 422
    assert len(calls) == before


def test_invalid_upstream_payload_returns_502(api_client) -> None:
    client, _ = api_client
    response = client.get("/api/v1/simulator/metrics")

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "INVALID_SIMULATOR_RESPONSE"


def test_dashboard_snapshot_returns_partial_state_and_resource_health(api_client) -> None:
    client, calls = api_client
    response = client.get(
        "/api/v1/dashboard/snapshot",
        params={"history_limit": 50, "station_id": "station-mirpur"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["instance"]["tick"] == 0
    assert body["as_of_tick"] == 0
    assert body["consistent"] is True
    assert body["complete"] is False  # Metrics are intentionally malformed in the mock.
    assert body["stale"] is True
    assert body["stations"][0]["id"] == "station-mirpur"
    assert body["resource_status"]["stations"]["status"] == "stale"
    assert body["resource_status"]["metrics"]["error_code"] == "INVALID_SIMULATOR_RESPONSE"
    assert response.headers["X-Simulator-Stale"] == "true"
    demand_request = next(call for call in calls if call.url.path == "/v1/demand-history")
    assert demand_request.url.params["limit"] == "50"
    assert demand_request.url.params["station_id"] == "station-mirpur"


def test_allocation_write_is_disabled_by_default(api_client) -> None:
    client, calls = api_client
    before = len(calls)
    response = client.post(
        "/api/v1/allocations",
        json={
            "idempotency_key": "op-test-11",
            "source_depot_id": "depot-gazipur",
            "destination_station_id": "station-mirpur",
            "route_id": "route-dhaka-mirpur",
            "fuel_type": "DIESEL",
            "quantity": 500,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SIMULATOR_WRITES_DISABLED"
    assert len(calls) == before


def test_operator_allocation_and_cancel_are_forwarded_when_enabled(api_client, monkeypatch) -> None:
    client, calls = api_client
    monkeypatch.setattr(operations, "SIMULATOR_WRITES_ENABLED", True)
    command = {
        "idempotency_key": "op-test-11",
        "source_depot_id": "depot-gazipur",
        "destination_station_id": "station-mirpur",
        "route_id": "route-dhaka-mirpur",
        "fuel_type": "DIESEL",
        "quantity": 500,
    }

    created = client.post("/api/v1/allocations", json=command)
    assert created.status_code == 201
    assert created.json()["status"] == "PENDING"
    assert created.json()["route_id"] == "route-dhaka-mirpur"
    create_request = next(call for call in calls if call.method == "POST")
    assert create_request.url.path == "/v1/allocations"
    assert json.loads(create_request.content) == command

    cancelled = client.post("/api/v1/allocations/11/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert calls[-1].url.path == "/v1/allocations/11/cancel"
    assert calls[-1].method == "POST"


def test_allocation_request_validation_rejects_bad_quantity(api_client) -> None:
    client, calls = api_client
    before = len(calls)
    response = client.post(
        "/api/v1/allocations",
        json={
            "idempotency_key": "op-test-invalid",
            "source_depot_id": "depot-gazipur",
            "destination_station_id": "station-mirpur",
            "route_id": "route-dhaka-mirpur",
            "fuel_type": "DIESEL",
            "quantity": 0,
        },
    )
    assert response.status_code == 422
    assert len(calls) == before


def test_unknown_upstream_entity_error_is_preserved(api_client) -> None:
    client, _ = api_client
    response = client.get("/api/v1/simulator/depots/not-a-depot")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SIMULATOR_REQUEST_FAILED"
    assert response.json()["detail"]["upstream_code"] == "NOT_FOUND"
    assert response.json()["detail"]["upstream_status"] == 404


@pytest.mark.parametrize("suffix", ["", "+00:00", "+06:00"])
def test_documented_sse_event_is_validated_and_relayed(suffix) -> None:
    sim_time = f"2026-01-01T00:45:00{suffix}"
    upstream = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=(
            "event: simulation.tick\n"
            f'data: {json.dumps({"tick": 3, "sim_time": sim_time})}\n\n'
            ": keepalive\n\n"
        ).encode(),
    )

    async def collect() -> bytes:
        return b"".join([chunk async for chunk in _validated_sse_body(upstream)])

    result = asyncio.run(collect()).decode()
    assert "event: simulation.tick" in result
    assert '"tick": 3' in result
    assert ": keepalive" in result
    assert sim_time in result
    assert "simulator.protocol_error" not in result


@pytest.mark.parametrize("api_client", ["invalid"], indirect=True)
@pytest.mark.parametrize("resource", ["instance", "demand-history"])
def test_invalid_simulator_timestamp_is_rejected(api_client, resource) -> None:
    client, _ = api_client
    response = client.get(f"/api/v1/simulator/{resource}")

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "INVALID_SIMULATOR_RESPONSE"


@pytest.mark.parametrize("payload", [{"tick": -1}, {"tick": 3, "sim_time": "invalid"}])
def test_invalid_sse_payload_becomes_protocol_error_event(payload) -> None:
    upstream = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=f"event: simulation.tick\ndata: {json.dumps(payload)}\n\n".encode(),
    )

    async def collect() -> bytes:
        return b"".join([chunk async for chunk in _validated_sse_body(upstream)])

    result = asyncio.run(collect()).decode()
    assert "event: simulator.protocol_error" in result
