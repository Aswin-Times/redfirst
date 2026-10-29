from fastapi.testclient import TestClient

from redfirst.api.app import create_app
from redfirst.core.config import Settings


def test_health(tmp_path):
    settings = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'h.db'}")
    r = TestClient(create_app(settings)).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
