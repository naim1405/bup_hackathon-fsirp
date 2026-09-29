"""Small WebSocket channel for notifying browsers to refresh REST state."""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["realtime"])


def _origin_allowed(origin: str | None) -> bool:
    """Accept configured browser origins; allow non-browser clients without Origin."""
    if not origin:
        return True
    configured = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173",
    )
    allowed = {item.strip().rstrip("/") for item in configured.split(",") if item.strip()}
    return origin.rstrip("/") in allowed


class WebSocketUpdateHub:
    """Fan out a tiny invalidation message; REST remains the source of truth."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        await websocket.send_json({"type": "connected"})

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def _broadcast(self, event: dict[str, str]) -> int:
        """Send a small event to all connected browsers and return deliveries."""
        async with self._lock:
            connections = tuple(self._connections)
            disconnected: list[WebSocket] = []
            delivered = 0
            for websocket in connections:
                try:
                    await websocket.send_json(event)
                    delivered += 1
                except Exception:  # connection may have closed between sends
                    disconnected.append(websocket)
            for websocket in disconnected:
                self._connections.discard(websocket)
            return delivered

    async def publish_update(self) -> None:
        """Tell clients that simulator-backed REST state may have changed."""
        await self._broadcast({"type": "update"})

    async def publish_decision_required(self) -> int:
        """Send a user-facing prompt to review a pending intelligence decision."""
        return await self._broadcast(
            {
                "type": "decision_required",
                "title": "Decision needed",
                "message": "A recommendation is ready for review. Please review it before approving or rejecting the plan.",
                "source": "manual_test",
            }
        )


@router.post(
    "/api/v1/realtime/test-decision-notification",
    summary="Send a test decision notification to connected dashboards",
    description=(
        "Broadcasts a sample decision-required prompt to all open dashboard WebSockets. "
        "This does not create a plan or change simulator state. The API currently "
        "has no operator authentication, so restrict access to trusted users."
    ),
)
async def test_decision_notification(request: Request) -> dict[str, object]:
    """Manually verify the WebSocket-to-dashboard decision prompt from Swagger."""
    hub: WebSocketUpdateHub | None = getattr(
        request.app.state, "websocket_update_hub", None
    )
    if hub is None:
        raise HTTPException(status_code=503, detail="Realtime notifications are unavailable.")

    delivered = await hub.publish_decision_required()
    return {
        "status": "sent",
        "type": "decision_required",
        "connected_clients": delivered,
        "message": "A recommendation is ready for review.",
    }


@router.websocket("/api/v1/ws")
async def simulator_updates(websocket: WebSocket) -> None:
    """Push refresh notifications; clients fetch the validated state over REST."""
    if not _origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return

    hub: WebSocketUpdateHub | None = getattr(
        websocket.app.state, "websocket_update_hub", None
    )
    if hub is None:
        await websocket.close(code=1011)
        return

    try:
        await hub.connect(websocket)
        while True:
            # The browser currently sends no commands; waiting here lets the
            # server notice disconnects while publish_update sends independently.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(websocket)
