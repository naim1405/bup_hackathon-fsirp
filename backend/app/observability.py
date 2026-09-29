from __future__ import annotations

import asyncio
import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import TypeAdapter

from app.simulator.client import SimulatorClient
from app.simulator.models import SimulatorInstance, SimulatorMetrics
from app.simulator.routes import get_simulator_client
from app.telemetry import telemetry

router = APIRouter(prefix="/api/v1", tags=["observability"])


@router.get("/status")
async def status(response: Response, client: SimulatorClient = Depends(get_simulator_client)) -> dict:
    response.headers["Cache-Control"] = "no-store"

    async def probe(path, model):
        try:
            result = await client.get_validated_result(path, TypeAdapter(model))
            return {"status": "stale" if result.stale else "healthy", "data": result.data.model_dump(mode="json")}
        except HTTPException as exc:
            return {"status": "unavailable", "error_code": exc.detail.get("code", "SIMULATOR_REQUEST_FAILED")}

    instance, metrics = await asyncio.gather(probe("/v1/instance", SimulatorInstance), probe("/v1/metrics", SimulatorMetrics))
    healthy = all(item["status"] == "healthy" for item in (instance, metrics))
    telemetry.health_transition("healthy" if healthy else "degraded")
    if not healthy:
        response.status_code = 503
    return {
        "status": "healthy" if healthy else "degraded",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "backend": "healthy",
        "simulator": instance,
        "simulation_metrics": metrics,
        "intelligence": {"status": "not_implemented"},
        "scope": "instance and metrics probes; not a guarantee for every simulator route",
    }


@router.get("/observability/metrics")
def metrics(response: Response, authorization: str | None = Header(default=None)) -> dict:
    token = os.getenv("OBSERVABILITY_TOKEN", "")
    if not token:
        raise HTTPException(503, detail="Metrics access is not configured")
    if not secrets.compare_digest((authorization or "").encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, detail="Invalid monitoring credential")
    response.headers["Cache-Control"] = "no-store"
    return telemetry.snapshot()
