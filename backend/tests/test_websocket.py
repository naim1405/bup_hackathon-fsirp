from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.websocket import WebSocketUpdateHub, router


def create_test_app() -> tuple[FastAPI, WebSocketUpdateHub]:
    app = FastAPI()
    hub = WebSocketUpdateHub()
    app.state.websocket_update_hub = hub
    app.include_router(router)

    @app.post("/publish")
    async def publish() -> dict[str, str]:
        await hub.publish_update()
        return {"status": "ok"}

    return app, hub


def test_websocket_sends_update_notifications() -> None:
    app, _ = create_test_app()

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/ws", headers={"Origin": "http://localhost:3000"}
        ) as websocket:
            assert websocket.receive_json() == {"type": "connected"}
            assert client.post("/publish").status_code == 200
            assert websocket.receive_json() == {"type": "update"}


def test_websocket_rejects_unconfigured_browser_origin() -> None:
    app, _ = create_test_app()

    with TestClient(app) as client:
        try:
            with client.websocket_connect(
                "/api/v1/ws", headers={"Origin": "https://untrusted.example"}
            ):
                raise AssertionError("untrusted origin should be rejected")
        except WebSocketDisconnect as exc:
            assert exc.code == 1008
