"""HTTP API: projects, uploads, investigations, worker hand-off, SSE and exports."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from redfirst.api.app import create_app
from redfirst.core.config import Settings
from redfirst.db.models import Base
from redfirst.db.session import make_engine
from redfirst.llm.fake import FakeProvider
from redfirst.llm.prompts import load_prompt
from redfirst.worker.orchestrator import Deps, Orchestrator
from redfirst.worker.queue import claim_next
from tests.conftest import local_executor, zip_fixture
from tests.integration.test_pipeline_e2e import BOUNDARY, REPORTS


@pytest.fixture
def ctx(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", reproduction_runs=1,
                        upload_max_bytes=200_000, worker_poll_seconds=0.1)
    engine = make_engine(f"sqlite:///{tmp_path / 'api.db'}")
    Base.metadata.create_all(engine)
    app = create_app(settings, engine)
    return TestClient(app), app, tmp_path


def upload(client, project_id, path):
    with open(path, "rb") as fh:
        return client.post(f"/api/projects/{project_id}/repositories",
                           files={"archive": ("repo.zip", fh, "application/zip")})


def new_project(client, name="demo"):
    r = client.post("/api/projects", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_project_crud_and_duplicate_name(ctx):
    client, _, _ = ctx
    pid = new_project(client)
    assert client.post("/api/projects", json={"name": "demo"}).status_code == 409
    assert client.post("/api/projects", json={"name": ""}).status_code == 422
    assert [p["id"] for p in client.get("/api/projects").json()] == [pid]


def test_full_flow_upload_investigate_report_export(ctx):
    client, app, tmp = ctx
    pid = new_project(client)
    r = upload(client, pid, zip_fixture("boundary_bug", tmp))
    assert r.status_code == 201, r.text
    repo = r.json()
    assert repo["layout"]["packages"] == ["shop"] and len(repo["sha256"]) == 64

    r = client.post(f"/api/projects/{pid}/investigations",
                    json={"repository_id": repo["id"], "bug_report": REPORTS["boundary_bug"]})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["state"] == "CREATED" and inv["outcome"] is None

    deps = Deps(settings=app.state.settings, engine=app.state.engine, blobs=app.state.blobs,
                provider=FakeProvider([BOUNDARY]), executor=local_executor,
                prompt=load_prompt("generate_test", "v1"),
                work_root=app.state.settings.data_dir / "work")
    assert claim_next(app.state.engine) == inv["id"]
    Orchestrator(deps, inv["id"]).run()

    detail = client.get(f"/api/investigations/{inv['id']}").json()
    assert (detail["outcome"], detail["outcome_reason"]) == ("REPRODUCED", "matching_failure")
    assert detail["attempts"][0]["executions"][0]["main_status"] == "failed"

    history = client.get("/api/investigations", params={"project_id": pid}).json()
    assert [h["outcome"] for h in history] == ["REPRODUCED"]

    test_file = client.get(f"/api/investigations/{inv['id']}/export/test")
    assert test_file.status_code == 200 and "def test_reproduces_bug" in test_file.text
    assert "attachment" in test_file.headers["content-disposition"]
    md = client.get(f"/api/investigations/{inv['id']}/export/report", params={"format": "md"})
    assert "**Outcome:** REPRODUCED" in md.text
    js = client.get(f"/api/investigations/{inv['id']}/export/report")
    assert js.json()["investigation_id"] == inv["id"]
    assert client.get(f"/api/investigations/{inv['id']}/export/report",
                      params={"format": "pdf"}).status_code == 400

    with client.stream("GET", f"/api/investigations/{inv['id']}/events") as stream:
        body = "".join(stream.iter_text())
    assert body.count("event: state") == 8 and "event: end" in body
    with client.stream("GET", f"/api/investigations/{inv['id']}/events",
                       headers={"Last-Event-ID": "7"}) as stream:
        assert "".join(stream.iter_text()).count("event: state") == 1

    assert client.post(f"/api/investigations/{inv['id']}/cancel").status_code == 409


def test_cancel_pending_investigation(ctx):
    client, _, tmp = ctx
    pid = new_project(client)
    repo = upload(client, pid, zip_fixture("no_bug", tmp)).json()
    inv = client.post(f"/api/projects/{pid}/investigations",
                      json={"repository_id": repo["id"], "bug_report": {"title": "x"}}).json()
    r = client.post(f"/api/investigations/{inv['id']}/cancel")
    assert r.status_code == 200 and r.json()["state"] == "CANCELLED"
    assert client.get(f"/api/investigations/{inv['id']}/export/test").status_code == 404


def test_malicious_archive_rejected(ctx):
    client, _, tmp = ctx
    pid = new_project(client)
    bad = tmp / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("a.py", "x = 1")
        zf.writestr("../escape.py", "x = 1")
    r = upload(client, pid, bad)
    assert r.status_code == 400 and "traversal" in r.json()["detail"]
    assert not (tmp / "data" / "escape.py").exists()


def test_upload_size_and_content_checks(ctx):
    client, _, tmp = ctx
    pid = new_project(client)
    big = tmp / "big.zip"
    with zipfile.ZipFile(big, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("a.py", "#" * 300_000)
    assert upload(client, pid, big).status_code == 413
    empty = tmp / "nopy.zip"
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("README.md", "hi")
    assert upload(client, pid, empty).status_code == 400
    r = client.post(f"/api/projects/{pid}/repositories",
                    files={"archive": ("x.zip", io.BytesIO(b"not a zip"), "application/zip")})
    assert r.status_code == 400


def test_validation_and_not_found(ctx):
    client, _, tmp = ctx
    p1, p2 = new_project(client, "one"), new_project(client, "two")
    repo = upload(client, p1, zip_fixture("no_bug", tmp)).json()
    r = client.post(f"/api/projects/{p2}/investigations",
                    json={"repository_id": repo["id"], "bug_report": {"title": "x"}})
    assert r.status_code == 400  # repository from another project
    r = client.post(f"/api/projects/{p1}/investigations",
                    json={"repository_id": repo["id"], "bug_report": {"title": ""}})
    assert r.status_code == 422
    assert client.get("/api/investigations/nope").status_code == 404
    assert client.get("/api/investigations/nope/events").status_code == 404
    assert upload(client, "nope", zip_fixture("no_bug", tmp)).status_code == 404
