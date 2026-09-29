import asyncio
import json

import httpx
import pytest

from app.main import app
from app.simulator.client import SimulatorClient
from app.simulator.routes import get_simulator_client
from app.telemetry import Telemetry, telemetry

INSTANCE = {"id": 1, "scenario_id": "baseline", "scenario_version": "1.0",
            "seed": 12345, "sim_time": "2026-01-01T00:00:00", "tick": 0,
            "tick_minutes": 15, "status": "PAUSED"}
METRICS = {"served_demand_liters": 0, "unmet_demand_liters": 0,
           "service_level": 1, "allocation_liters": 0, "allocation_failures": 0}


def request(path, handler=None, headers=None):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler or (lambda r: httpx.Response(503))), base_url="http://simulator") as upstream:
            app.dependency_overrides[get_simulator_client] = lambda: SimulatorClient(upstream)
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api:
                    return await api.get(path, headers=headers)
            finally:
                app.dependency_overrides.clear()
    return asyncio.run(run())


def healthy(req):
    return httpx.Response(200, json=INSTANCE if req.url.path == "/v1/instance" else METRICS)


def test_status_paused_naive_timestamp_is_healthy():
    result = request("/api/v1/status", healthy)
    assert result.status_code == 200
    assert result.json()["status"] == "healthy"
    assert result.json()["intelligence"]["status"] == "not_implemented"
    assert result.headers["cache-control"] == "no-store"
    assert len(result.headers["x-request-id"]) == 32


@pytest.mark.parametrize("mode", ["unavailable", "invalid", "stale", "timeout"])
def test_degradation_and_recovery(mode):
    def failed(req):
        if mode == "timeout":
            raise httpx.ReadTimeout("private upstream detail", request=req)
        if mode == "unavailable":
            return httpx.Response(503)
        if mode == "invalid":
            return httpx.Response(200, json={"secret": "must-not-log"})
        result = healthy(req)
        result.headers["X-Simulator-Stale"] = "true"
        return result
    assert request("/api/v1/health", failed).status_code == 200
    degraded = request("/api/v1/status", failed)
    assert degraded.status_code == 503
    assert degraded.json()["status"] == "degraded"
    assert "private upstream detail" not in degraded.text
    assert request("/api/v1/status", healthy).status_code == 200


def test_metrics_fail_closed_and_require_secret(monkeypatch):
    monkeypatch.delenv("OBSERVABILITY_TOKEN", raising=False)
    assert request("/api/v1/observability/metrics").status_code == 503
    monkeypatch.setenv("OBSERVABILITY_TOKEN", "test-only")
    assert request("/api/v1/observability/metrics").status_code == 401
    result = request("/api/v1/observability/metrics", headers={"Authorization": "Bearer test-only"})
    assert result.status_code == 200
    assert "test-only" not in result.text


def test_bounded_latency_and_stream_exclusion():
    meter = Telemetry()
    for _ in range(1100):
        meter.request("/known/{id}", 200, .1, False)
    meter.request("/stream", 200, 1000, True)
    data = meter.snapshot()
    assert data["latency_samples"] == 1000
    assert data["latency_p99_ms"] == 100
    assert data["counters"]["requests_total"] == 1101


def test_logs_exclude_query_body_and_credentials(monkeypatch):
    records = []
    monkeypatch.setattr("app.telemetry.logger.info", records.append)
    request("/does-not-exist?token=secret-value", headers={"Authorization": "Bearer secret-value"})
    assert "secret-value" not in "".join(records)
    event = json.loads(records[-1])
    assert event["route"] == "unmatched"
    assert event["status"] == 404


def test_invalid_response_counter():
    before = telemetry.snapshot()["counters"].get("simulator_invalid_total", 0)
    request("/api/v1/status", lambda req: httpx.Response(200, json={}))
    assert telemetry.snapshot()["counters"]["simulator_invalid_total"] == before + 2
