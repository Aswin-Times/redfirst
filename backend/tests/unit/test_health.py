from fastapi.testclient import TestClient

from redfirst.api.app import create_app


def test_health():
    r = TestClient(create_app()).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
