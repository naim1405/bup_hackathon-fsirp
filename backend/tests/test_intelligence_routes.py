"""HTTP-level tests for the intelligence routes (through FastAPI)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.intelligence.config import PolicyConfig
from app.intelligence.models import PlanStatus
from app.intelligence.service import IntelligenceEngine
from app.main import app
from tests.test_intelligence_service import FakeSimulator, make_policy


@pytest.fixture
def api(world_and_engine):
    _, engine = world_and_engine
    app.state.intelligence = engine

    def call(method: str, path: str, json_body: dict | None = None) -> httpx.Response:
        async def request() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, json=json_body)

        return asyncio.run(request())

    return call


@pytest.fixture
def world_and_engine(tmp_path):
    world = FakeSimulator()
    policy = make_policy(tmp_path)
    transport = httpx.MockTransport(world.handler)
    engine = IntelligenceEngine(
        httpx.AsyncClient(transport=transport, base_url="http://s"),
        policy,
        simulator_writes_enabled=True,
    )
    return world, engine


class TestRoutes:
    def test_endpoints_before_first_run(self, api) -> None:
        assert api("GET", "/api/v1/intelligence/status").status_code == 200
        assert api("GET", "/api/v1/intelligence/prediction").status_code == 503
        assert api("GET", "/api/v1/intelligence/detection").status_code == 503
        assert api("GET", "/api/v1/intelligence/recommendations").status_code == 503

    def test_full_operator_flow_over_http(self, api, world_and_engine) -> None:
        world, engine = world_and_engine
        run_response = api("POST", "/api/v1/intelligence/run", {"force": True})
        assert run_response.status_code == 200
        assert run_response.json()["has_plan"] is True

        prediction = api("GET", "/api/v1/intelligence/prediction")
        assert prediction.status_code == 200
        body = prediction.json()
        assert len(body["forecasts"]) == 12
        assert body["risk_by_station"]

        detection = api("GET", "/api/v1/intelligence/detection")
        assert detection.status_code == 200

        alerts = api("GET", "/api/v1/intelligence/alerts")
        assert alerts.status_code == 200

        recs = api("GET", "/api/v1/intelligence/recommendations")
        assert recs.status_code == 200
        plan = recs.json()

        world.create_shortage("station-mirpur", "DIESEL", 300.0)
        api("POST", "/api/v1/intelligence/run", {"force": True})
        plan = api("GET", "/api/v1/intelligence/recommendations").json()
        assert plan["recommendations"], "shortage must produce a recommendation"

        approved = api(
            "POST",
            f"/api/v1/intelligence/plans/{plan['plan_id']}/approve",
            {"operator": "op-1"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == PlanStatus.APPROVED.value

        executed = api(
            "POST",
            f"/api/v1/intelligence/plans/{plan['plan_id']}/execute",
            {"operator": "op-1"},
        )
        assert executed.status_code == 200
        assert executed.json()["status"] == PlanStatus.APPLIED.value
        assert world.post_bodies

    def test_execute_unknown_plan_404(self, api) -> None:
        response = api(
            "POST",
            "/api/v1/intelligence/plans/does-not-exist/execute",
            {"operator": "op-1"},
        )
        assert response.status_code == 404

    def test_alert_acknowledge(self, api, world_and_engine) -> None:
        world, engine = world_and_engine
        api("POST", "/api/v1/intelligence/run", {"force": True})
        world.create_shortage("station-mirpur", "DIESEL", 300.0)
        api("POST", "/api/v1/intelligence/run", {"force": True})
        alerts = api("GET", "/api/v1/intelligence/alerts").json()
        target = next(a for a in alerts if a["state"] == "active")
        finding_id = target["finding"]["finding_id"]
        ack = api(
            "POST",
            f"/api/v1/intelligence/alerts/{finding_id}/acknowledge",
            {"operator": "op-1", "comment": "reviewed"},
        )
        assert ack.status_code == 200
        assert ack.json()["state"] == "acknowledged"
