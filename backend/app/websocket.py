"""Small WebSocket channel for notifying browsers to refresh REST state."""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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

    async def publish_update(self) -> None:
        """Tell connected clients that simulator-backed REST state may have changed."""
        async with self._lock:
            connections = tuple(self._connections)
            disconnected: list[WebSocket] = []
            for websocket in connections:
                try:
                    await websocket.send_json({"type": "update"})
                except Exception:  # connection may have closed between sends
                    disconnected.append(websocket)
            for websocket in disconnected:
                self._connections.discard(websocket)


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
