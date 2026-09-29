from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_returns_service_information() -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "fsirp-backend"
    assert body["status"] == "ok"
    assert body["docs"] == "/docs"


def test_health_endpoint() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "fsirp-backend"}


def test_health_alias() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
