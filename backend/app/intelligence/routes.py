"""HTTP API for the intelligence engine (read + operator approval actions).

All endpoints live under ``/api/v1/intelligence``. The engine never mutates
simulator state from a GET; the only simulator writes happen through
``POST /plans/{plan_id}/execute`` after explicit operator approval and only
when ``INTELLIGENCE_EXECUTION_ENABLED`` is true.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.intelligence.service import IntelligenceEngine


async def get_engine(request: Request) -> IntelligenceEngine:
    engine: IntelligenceEngine | None = getattr(request.app.state, "intelligence", None)
    if engine is None:
        raise HTTPException(status_code=503, detail={"code": "ENGINE_UNAVAILABLE"})
    return engine


router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])


class RunRequest(BaseModel):
    force: bool = Field(
        default=False,
        description="Recompute even if this simulator tick was already processed.",
    )


class OperatorRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=120, description="Operator identifier for the audit trail.")
    comment: str | None = Field(default=None, max_length=500)


@router.get(
    "/status",
    summary="Engine status and training health",
    description="Component health for the status panel: last run, training state, fallback flag.",
)
async def status(engine: Annotated[IntelligenceEngine, Depends(get_engine)]) -> Any:
    return engine.status()


@router.get(
    "/prediction",
    summary="Latest demand forecast, inventory projection, and risk map",
)
async def prediction(engine: Annotated[IntelligenceEngine, Depends(get_engine)]) -> Any:
    if engine.latest.prediction is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "NO_PREDICTION_YET", "message": "The engine has not completed a run yet."},
        )
    return engine.latest.prediction


@router.get(
    "/detection",
    summary="Latest detection findings (observed + predictive)",
)
async def detection(engine: Annotated[IntelligenceEngine, Depends(get_engine)]) -> Any:
    if engine.latest.detection is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "NO_DETECTION_YET", "message": "The engine has not completed a run yet."},
        )
    return engine.latest.detection


@router.get(
    "/alerts",
    summary="Alert registry with lifecycle states",
)
async def alerts(
    engine: Annotated[IntelligenceEngine, Depends(get_engine)],
    state: Annotated[str | None, Query(pattern="^(active|acknowledged|resolved|run_ended)$")] = None,
) -> Any:
    return [
        {
            "finding": record.finding.model_dump(mode="json"),
            "state": record.state,
            "acknowledged_by": record.acknowledged_by,
            "acknowledged_at_epoch": record.acknowledged_at_epoch,
            "acknowledged_comment": record.acknowledged_comment,
        }
        for record in engine.list_alerts(state)
    ]


@router.post(
    "/alerts/{finding_id}/acknowledge",
    summary="Acknowledge an alert (operator action, audit-logged)",
)
async def acknowledge(
    finding_id: str,
    body: OperatorRequest,
    engine: Annotated[IntelligenceEngine, Depends(get_engine)],
) -> Any:
    try:
        record = engine.acknowledge_alert(finding_id, body.operator, body.comment)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "ALERT_NOT_FOUND"}) from exc
    return {
        "finding_id": finding_id,
        "state": record.state,
        "acknowledged_by": record.acknowledged_by,
        "acknowledged_at_epoch": record.acknowledged_at_epoch,
    }


@router.get(
    "/recommendations",
    summary="Latest proposed plan (recommendations + impact + no-action reasons)",
)
async def recommendations(engine: Annotated[IntelligenceEngine, Depends(get_engine)]) -> Any:
    plan = engine.current_plan()
    if plan is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "NO_PLAN_YET", "message": "The engine has not completed a run yet."},
        )
    return plan


@router.get(
    "/plans/{plan_id}",
    summary="Fetch a specific plan (including its execution outcomes)",
)
async def get_plan(plan_id: str, engine: Annotated[IntelligenceEngine, Depends(get_engine)]) -> Any:
    plan = engine.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail={"code": "PLAN_NOT_FOUND"})
    return plan


@router.post("/run", summary="Trigger an engine run now")
async def run(
    body: RunRequest | None = None,
    engine: Annotated[IntelligenceEngine, Depends(get_engine)] = None,  # type: ignore[assignment]
) -> Any:
    results = await engine.run_once(force=bool(body.force if body else False))
    return {
        "snapshot_id": results.snapshot_id,
        "generated_at_epoch": results.generated_at_epoch,
        "has_prediction": results.prediction is not None,
        "has_detection": results.detection is not None,
        "has_plan": results.plan is not None,
        "plan_id": results.plan.plan_id if results.plan else None,
    }


@router.post(
    "/plans/{plan_id}/approve",
    summary="Approve a plan for submission (operator action)",
)
async def approve(
    plan_id: str,
    body: OperatorRequest,
    engine: Annotated[IntelligenceEngine, Depends(get_engine)],
) -> Any:
    try:
        plan = engine.approve_plan(plan_id, body.operator)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "PLAN_NOT_FOUND"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "PLAN_NOT_APPROVABLE", "message": str(exc)}) from exc
    return plan


@router.post(
    "/plans/{plan_id}/reject",
    summary="Reject a plan (operator action)",
)
async def reject(
    plan_id: str,
    body: OperatorRequest,
    engine: Annotated[IntelligenceEngine, Depends(get_engine)],
) -> Any:
    try:
        return engine.reject_plan(plan_id, body.operator)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "PLAN_NOT_FOUND"}) from exc


@router.post(
    "/plans/{plan_id}/execute",
    summary=(
        "Submit an approved plan to the simulator. Requires "
        "INTELLIGENCE_EXECUTION_ENABLED=true; revalidates state first; "
        "allocations are created with stable idempotency keys."
    ),
)
async def execute(
    plan_id: str,
    body: OperatorRequest,
    engine: Annotated[IntelligenceEngine, Depends(get_engine)],
) -> Any:
    try:
        return await engine.execute_plan(plan_id, body.operator)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "PLAN_NOT_FOUND"}) from exc
