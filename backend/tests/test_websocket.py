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

    return app, hub


def test_swagger_test_endpoint_sends_decision_notification() -> None:
    app, _ = create_test_app()

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/ws", headers={"Origin": "http://localhost:3000"}
        ) as websocket:
            assert websocket.receive_json() == {"type": "connected"}
            response = client.post("/api/v1/realtime/test-decision-notification")
            assert response.status_code == 200
            assert response.json()["connected_clients"] == 1
            event = websocket.receive_json()
            assert event["type"] == "decision_required"
            assert event["title"] == "Decision needed"
            assert event["source"] == "manual_test"


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
