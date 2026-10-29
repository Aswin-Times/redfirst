"""HTTP routes. The API never executes repository code; the worker does, in the sandbox."""

import json
import shutil
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from redfirst.api.schemas import (
    InvestigationIn,
    InvestigationOut,
    ProjectIn,
    ProjectOut,
    RepositoryOut,
)
from redfirst.db import service
from redfirst.db.models import BugReport, Investigation, InvestigationEvent, Project, Repository
from redfirst.db.session import session_scope
from redfirst.domain.enums import InvestigationState as S
from redfirst.domain.state_machine import is_terminal
from redfirst.repos.extract import UnsafeArchive, extract_archive
from redfirst.repos.layout import detect_layout
from redfirst.verification.report import build_report, render_markdown

router = APIRouter(prefix="/api")


def _session(request: Request):
    return session_scope(request.app.state.engine)


def _get(s: Session, model, id_: str):
    obj = s.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} not found")
    return obj


def _inv_out(s: Session, inv: Investigation) -> InvestigationOut:
    report = s.get(BugReport, inv.bug_report_id)
    return InvestigationOut(
        id=inv.id, project_id=report.project_id, repository_id=inv.repository_id,
        title=report.title, state=inv.state.value,
        outcome=inv.outcome.value if inv.outcome else None,
        outcome_reason=inv.outcome_reason.value if inv.outcome_reason else None,
        created_at=inv.created_at, updated_at=inv.updated_at, completed_at=inv.completed_at,
    )


# -- projects -----------------------------------------------------------------------------------
@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, request: Request):
    try:
        with _session(request) as s:
            project = Project(name=body.name)
            s.add(project)
            s.flush()
            return ProjectOut.model_validate(project)
    except IntegrityError as exc:
        raise HTTPException(409, "a project with this name already exists") from exc


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(request: Request):
    with _session(request) as s:
        return [ProjectOut.model_validate(p)
                for p in s.scalars(select(Project).order_by(Project.created_at))]


# -- repositories -------------------------------------------------------------------------------
@router.post("/projects/{project_id}/repositories", response_model=RepositoryOut,
             status_code=201)
def upload_repository(project_id: str, request: Request,
                      archive: Annotated[UploadFile, File()]):
    settings = request.app.state.settings
    with _session(request) as s:
        _get(s, Project, project_id)

    tmp_root = settings.data_dir / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=tmp_root))
    try:
        upload = tmp / "upload.bin"
        size = 0
        with open(upload, "wb") as out:
            while chunk := archive.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.upload_max_bytes:
                    raise HTTPException(413, "archive exceeds the upload size limit")
                out.write(chunk)
        try:  # validate by extracting once with all safety limits
            extract_archive(upload, tmp / "check")
        except UnsafeArchive as exc:
            raise HTTPException(400, f"archive rejected: {exc}") from exc
        layout = detect_layout(tmp / "check")
        if layout.python_file_count == 0:
            raise HTTPException(400, "archive contains no Python files")
        key = request.app.state.blobs.put_file(upload)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    with _session(request) as s:
        repo = Repository(project_id=project_id, source_type="archive", storage_ref=key,
                          sha256=key, layout=layout.model_dump())
        s.add(repo)
        s.flush()
        return RepositoryOut.model_validate(repo)


@router.get("/projects/{project_id}/repositories", response_model=list[RepositoryOut])
def list_repositories(project_id: str, request: Request):
    with _session(request) as s:
        _get(s, Project, project_id)
        rows = s.scalars(select(Repository).where(Repository.project_id == project_id)
                         .order_by(Repository.created_at))
        return [RepositoryOut.model_validate(r) for r in rows]


# -- investigations -----------------------------------------------------------------------------
@router.post("/projects/{project_id}/investigations", response_model=InvestigationOut,
             status_code=201)
def create_investigation(project_id: str, body: InvestigationIn, request: Request):
    with _session(request) as s:
        _get(s, Project, project_id)
        repo = _get(s, Repository, body.repository_id)
        if repo.project_id != project_id:
            raise HTTPException(400, "repository belongs to a different project")
        report = BugReport(project_id=project_id, **body.bug_report.model_dump())
        s.add(report)
        s.flush()
        inv = service.create_investigation(s, report.id, repo.id)
        return _inv_out(s, inv)


@router.get("/investigations", response_model=list[InvestigationOut])
def list_investigations(request: Request, project_id: str | None = None, limit: int = 50):
    with _session(request) as s:
        q = select(Investigation).order_by(Investigation.created_at.desc()).limit(min(limit, 200))
        if project_id:
            q = q.join(BugReport, BugReport.id == Investigation.bug_report_id) \
                 .where(BugReport.project_id == project_id)
        return [_inv_out(s, inv) for inv in s.scalars(q)]


@router.get("/investigations/{inv_id}")
def get_investigation(inv_id: str, request: Request):
    with _session(request) as s:
        return build_report(s, _get(s, Investigation, inv_id)).model_dump(mode="json")


@router.post("/investigations/{inv_id}/cancel", response_model=InvestigationOut)
def cancel_investigation(inv_id: str, request: Request):
    with _session(request) as s:
        inv = _get(s, Investigation, inv_id)
        if is_terminal(inv.state):
            raise HTTPException(409, f"investigation already {inv.state.value}")
        service.transition(s, inv, S.CANCELLED, "cancelled by user")
        return _inv_out(s, inv)


@router.get("/investigations/{inv_id}/events")
def stream_events(inv_id: str, request: Request):
    """Server-Sent Events from the persisted event log; ends once the investigation is final."""
    engine = request.app.state.engine
    poll = request.app.state.settings.worker_poll_seconds / 2
    with _session(request) as s:
        _get(s, Investigation, inv_id)
    header = request.headers.get("last-event-id", "0")
    last_id = int(header) if header.isdigit() else 0

    def gen() -> Iterator[str]:
        nonlocal last_id
        idle = 0.0
        while True:
            with session_scope(engine) as s:
                events = s.scalars(select(InvestigationEvent).where(
                    InvestigationEvent.investigation_id == inv_id,
                    InvestigationEvent.id > last_id).order_by(InvestigationEvent.id)).all()
                state = s.get(Investigation, inv_id).state
                for e in events:
                    last_id = e.id
                    data = {"state": e.to_state.value, "message": e.message, "data": e.data,
                            "at": e.created_at.isoformat()}
                    yield f"id: {e.id}\nevent: state\ndata: {json.dumps(data)}\n\n"
            if is_terminal(state):
                yield "event: end\ndata: {}\n\n"
                return
            time.sleep(poll)
            idle += poll
            if idle >= 15:  # keep proxies from closing the connection
                idle = 0.0
                yield ": keep-alive\n\n"

    # no-transform stops compressing proxies (e.g. the Next.js dev proxy) from buffering
    # the stream; X-Accel-Buffering does the same for nginx.
    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@router.get("/investigations/{inv_id}/export/test")
def export_test(inv_id: str, request: Request):
    with _session(request) as s:
        report = build_report(s, _get(s, Investigation, inv_id))
    if not report.final_test:
        raise HTTPException(404, "no executed test for this investigation")
    return Response(report.final_test, media_type="text/x-python", headers={
        "Content-Disposition": f'attachment; filename="test_redfirst_{inv_id[:8]}.py"'})


@router.get("/investigations/{inv_id}/export/report")
def export_report(inv_id: str, request: Request, format: str = "json"):
    with _session(request) as s:
        report = build_report(s, _get(s, Investigation, inv_id))
    if format == "md":
        return PlainTextResponse(render_markdown(report), media_type="text/markdown", headers={
            "Content-Disposition": f'attachment; filename="redfirst_{inv_id[:8]}.md"'})
    if format != "json":
        raise HTTPException(400, "format must be json or md")
    return Response(report.model_dump_json(indent=2), media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="redfirst_{inv_id[:8]}.json"'})
