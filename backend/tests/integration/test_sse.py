"""D10: Server-Sent Events must not tie up worker threads, and must stop on disconnect.

The concurrency test runs a real uvicorn server in a background thread with the thread pool
limited to 2, opens two idle event streams, and checks an ordinary (threadpool-backed) API
request still completes promptly.
"""

import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager

import anyio.to_thread
import httpx
import pytest
import uvicorn

from redfirst.api import routes
from redfirst.api.app import create_app
from redfirst.core.config import Settings
from redfirst.db import service
from redfirst.db.models import Base, BugReport, Investigation, Project, Repository
from redfirst.db.session import make_engine, session_scope
from redfirst.domain.enums import InvestigationState as S


class LimitThreads:
    """ASGI wrapper that shrinks the default thread pool inside the server's event loop."""

    def __init__(self, app, tokens: int) -> None:
        self.app, self.tokens, self.applied = app, tokens, False

    async def __call__(self, scope, receive, send):
        if not self.applied:
            anyio.to_thread.current_default_thread_limiter().total_tokens = self.tokens
            self.applied = True
        await self.app(scope, receive, send)


@contextmanager
def live_server(app):
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "uvicorn did not start"
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture
def setup(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", worker_poll_seconds=0.2)
    engine = make_engine(f"sqlite:///{tmp_path / 'sse.db'}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as s:
        project = Project(name="p")
        s.add(project)
        s.flush()
        report = BugReport(project_id=project.id, title="t")
        repo = Repository(project_id=project.id, source_type="archive", storage_ref="x")
        s.add_all([report, repo])
        s.flush()
        inv_id = service.create_investigation(s, report.id, repo.id).id  # stays CREATED: idle
    yield create_app(settings, engine), engine, inv_id
    engine.dispose()


def test_idle_event_streams_do_not_starve_other_requests(setup):
    app, _, inv_id = setup
    stop = threading.Event()
    opened = threading.Barrier(3, timeout=10)

    def hold_stream(base: str) -> None:
        with httpx.Client(base_url=base, timeout=30) as c, \
                c.stream("GET", f"/api/investigations/{inv_id}/events") as r:
            lines = r.iter_lines()
            while next(lines) != "":  # consume the first (CREATED) event
                pass
            opened.wait()
            stop.wait(30)

    with live_server(LimitThreads(app, tokens=2)) as base:
        holders = [threading.Thread(target=hold_stream, args=(base,), daemon=True)
                   for _ in range(2)]
        for h in holders:
            h.start()
        opened.wait()  # both streams are open and idle
        started = time.monotonic()
        response = httpx.get(f"{base}/api/projects", timeout=10)
        elapsed = time.monotonic() - started
        stop.set()
        assert response.status_code == 200
        assert elapsed < 3, f"a normal request waited {elapsed:.1f}s behind idle event streams"
        for h in holders:
            h.join(timeout=10)


def test_stream_delivers_events_after_last_event_id_and_ends_when_terminal(setup):
    _, engine, inv_id = setup
    with session_scope(engine) as s:
        inv = s.get(Investigation, inv_id)
        service.transition(s, inv, S.ANALYZING_REPORT)
        service.transition(s, inv, S.CANCELLED)

    async def collect(last_id: int) -> list[str]:
        async def connected() -> bool:
            return False
        return [chunk async for chunk in routes.event_stream(engine, inv_id, last_id, 0.01,
                                                              connected)]

    chunks = asyncio.run(collect(0))
    states = [json.loads(c.split("data: ", 1)[1])["state"] for c in chunks if "event: state" in c]
    assert states == ["CREATED", "ANALYZING_REPORT", "CANCELLED"]
    assert chunks[-1].startswith("event: end")
    first_id = int(chunks[0].split("\n", 1)[0].removeprefix("id: "))
    resumed = asyncio.run(collect(first_id))
    assert sum("event: state" in c for c in resumed) == 2  # only events after Last-Event-ID


def test_stream_stops_when_the_client_disconnects(setup, monkeypatch):
    _, engine, inv_id = setup
    polls = []
    real = routes._load_events

    def counting(*args):
        polls.append(1)
        return real(*args)

    monkeypatch.setattr(routes, "_load_events", counting)
    checks = iter([False, False, True])  # client goes away before the third poll

    async def disconnected() -> bool:
        return next(checks, True)

    async def drain() -> list[str]:
        return [c async for c in routes.event_stream(engine, inv_id, 0, 0.01, disconnected)]

    chunks = asyncio.run(drain())
    assert len(polls) == 2 and sum("event: state" in c for c in chunks) == 1


def test_stream_for_an_investigation_deleted_mid_stream_ends_cleanly(setup):
    _, engine, inv_id = setup
    with session_scope(engine) as s:
        inv = s.get(Investigation, inv_id)
        service.transition(s, inv, S.CANCELLED)
    from redfirst.db.retention import delete_investigation

    with session_scope(engine) as s:
        delete_investigation(s, s.get(Investigation, inv_id))

    async def connected() -> bool:
        return False

    async def drain() -> list[str]:
        return [c async for c in routes.event_stream(engine, inv_id, 0, 0.01, connected)]

    assert asyncio.run(drain()) == ["event: end\ndata: {}\n\n"]
