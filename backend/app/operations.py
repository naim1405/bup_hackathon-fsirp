"""Frontend-facing allocation read and operator command endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import TypeAdapter

from app.simulator.client import SimulatorClient
from app.simulator.config import SIMULATOR_WRITES_ENABLED
from app.simulator.models import Allocation, AllocationCreateRequest
from app.simulator.routes import get_simulator_client

router = APIRouter(prefix="/api/v1", tags=["operations"])


def _require_writes_enabled() -> None:
    if not SIMULATOR_WRITES_ENABLED:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SIMULATOR_WRITES_DISABLED",
                "message": "Simulator write operations are disabled. Enable them explicitly for a trusted operator environment.",
            },
        )


@router.get("/allocations", response_model=list[Allocation], summary="List allocations for the frontend")
async def list_allocations(
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> list[Allocation]:
    """Read current allocation state from the simulator without local duplication."""
    return await client.get_validated("/v1/allocations", TypeAdapter(list[Allocation]), response)


@router.post(
    "/allocations",
    response_model=Allocation,
    status_code=201,
    summary="Create an operator-approved allocation",
)
async def create_allocation(
    command: AllocationCreateRequest,
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> Allocation:
    """Forward one explicit operator command; this endpoint does not recommend actions."""
    _require_writes_enabled()
    return await client.post_validated(
        "/v1/allocations",
        command.model_dump(mode="json"),
        TypeAdapter(Allocation),
        response,
    )


@router.post(
    "/allocations/{allocation_id}/cancel",
    response_model=Allocation,
    summary="Cancel a pending allocation",
)
async def cancel_allocation(
    allocation_id: Annotated[int, Path(gt=0)],
    response: Response,
    client: Annotated[SimulatorClient, Depends(get_simulator_client)],
) -> Allocation:
    """Forward an explicit cancellation request and validate the simulator result."""
    _require_writes_enabled()
    return await client.post_validated(
        f"/v1/allocations/{allocation_id}/cancel",
        None,
        TypeAdapter(Allocation),
        response,
    )
