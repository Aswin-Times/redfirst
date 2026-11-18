import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from redfirst.db import service
from redfirst.db.models import (
    Base,
    BugReport,
    EvidenceRecord,
    Investigation,
    InvestigationEvent,
    Project,
    Repository,
)
from redfirst.db.session import make_engine, session_scope
from redfirst.domain.enums import InvestigationState as S
from redfirst.domain.enums import Outcome, OutcomeReason
from redfirst.domain.state_machine import InvalidTransition


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def seed(session, name="demo"):
    project = Project(name=name)
    session.add(project)
    session.flush()
    report = BugReport(project_id=project.id, title="crash", missing_fields=["stack_trace"])
    repo = Repository(project_id=project.id, source_type="archive", storage_ref="blobs/ab/cd")
    session.add_all([report, repo])
    session.flush()
    return service.create_investigation(session, report.id, repo.id)


def test_alembic_migration_matches_models(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    cfg = Config("alembic.ini")
    cfg.attributes["engine"] = eng
    command.upgrade(cfg, "head")
    assert set(inspect(eng).get_table_names()) - {"alembic_version"} == set(Base.metadata.tables)
    # Column-level check: the migrated schema must match the models exactly (catches a model
    # change without a migration, e.g. the M9 lease columns).
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    with eng.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diffs == [], diffs
    command.downgrade(cfg, "0001")
    columns = {c["name"] for c in inspect(eng).get_columns("investigations")}
    assert not {"worker_id", "lease_expires_at"} & columns
    command.downgrade(cfg, "base")
    assert set(inspect(eng).get_table_names()) == {"alembic_version"}
    eng.dispose()


def test_investigation_lifecycle_records_events(engine):
    with session_scope(engine) as s:
        inv = seed(s)
        for state in (S.ANALYZING_REPORT, S.ANALYZING_REPOSITORY, S.GENERATING_TEST,
                      S.VALIDATING_TEST, S.EXECUTING_TEST, S.VERIFYING_RESULT):
            service.transition(s, inv, state)
        service.complete(s, inv, Outcome.NOT_REPRODUCED, OutcomeReason.NO_FAILURE_OBSERVED)
        inv_id = inv.id
    with session_scope(engine) as s:
        events = s.scalars(select(InvestigationEvent).order_by(InvestigationEvent.id)).all()
        assert [e.to_state for e in events][0] == S.CREATED
        assert events[-1].to_state == S.COMPLETED and events[-1].data["outcome"] == "NOT_REPRODUCED"
        inv = s.get(type(inv), inv_id)
        assert inv.state == S.COMPLETED and inv.completed_at is not None


def test_illegal_transition_is_rejected_and_not_recorded(engine):
    with session_scope(engine) as s:
        inv = seed(s)
        with pytest.raises(InvalidTransition):
            service.transition(s, inv, S.EXECUTING_TEST)
        assert inv.state == S.CREATED
        assert len(inv.events) == 1


def test_fail_records_error_and_execution_error_outcome(engine):
    with session_scope(engine) as s:
        inv = seed(s)
        service.transition(s, inv, S.ANALYZING_REPORT)
        service.fail(s, inv, {"type": "SandboxError", "detail": "docker unavailable"})
        assert (inv.state, inv.outcome) == (S.FAILED, Outcome.EXECUTION_ERROR)
        assert inv.error["type"] == "SandboxError"
        with pytest.raises(ValueError):
            service.complete(s, inv, Outcome.EXECUTION_ERROR, OutcomeReason.RUNNER_FAILURE)


def test_attempts_are_bounded(engine):
    with session_scope(engine) as s:
        inv = seed(s)
        assert service.start_attempt(s, inv, 2).number == 1
        assert service.start_attempt(s, inv, 2).number == 2
        with pytest.raises(ValueError, match="limit"):
            service.start_attempt(s, inv, 2)


def test_unfinished_investigations_survive_restart(engine):
    with session_scope(engine) as s:
        a, b = seed(s, "p1"), seed(s, "p2")
        service.transition(s, b, S.ANALYZING_REPORT)
        service.transition(s, b, S.CANCELLED)
        pending_id = a.id
    with session_scope(engine) as s:  # a "restarted" process with fresh sessions
        assert [i.id for i in service.find_unfinished(s)] == [pending_id]


def test_failed_transaction_rolls_back(engine):
    with pytest.raises(RuntimeError), session_scope(engine) as s:
        seed(s)
        raise RuntimeError("boom")
    with session_scope(engine) as s:
        assert s.scalars(select(Project)).all() == []


def test_foreign_keys_enforced(engine):
    with pytest.raises(IntegrityError), session_scope(engine) as s:
        s.add(EvidenceRecord(investigation_id="missing", kind="x", payload={}))


# --- D11: retention must delete evidence before the execution results it references ------------
def test_delete_removes_evidence_that_references_execution_results(engine):
    from redfirst.db.models import Attempt, ExecutionResult
    from redfirst.db.retention import delete_investigation

    with session_scope(engine) as s:
        inv = seed(s)
        attempt = service.start_attempt(s, inv, 3)
        run = ExecutionResult(attempt_id=attempt.id, run_index=0, exit_code=1,
                              stdout_ref="a" * 64, stderr_ref="b" * 64, junit_ref="c" * 64)
        s.add(run)
        s.flush()
        s.add(EvidenceRecord(investigation_id=inv.id, kind="verdict", payload={"x": 1},
                             execution_result_id=run.id, artifact_ref="d" * 64))
        service.transition(s, inv, S.CANCELLED)
        inv_id = inv.id
    with session_scope(engine) as s:  # foreign keys are enforced (PRAGMA foreign_keys=ON)
        refs = delete_investigation(s, s.get(Investigation, inv_id))
    assert refs == {"a" * 64, "b" * 64, "c" * 64, "d" * 64}
    with session_scope(engine) as s:
        assert s.scalars(select(EvidenceRecord)).all() == []
        assert s.scalars(select(ExecutionResult)).all() == []
        assert s.scalars(select(Attempt)).all() == []
        assert s.get(Investigation, inv_id) is None


def test_blob_sweep_preserves_shared_junit_and_evidence_artifacts(engine, tmp_path):
    from redfirst.db.models import ExecutionResult
    from redfirst.db.retention import sweep_blobs
    from redfirst.storage.blobs import BlobStore

    blobs = BlobStore(tmp_path / "blobs")
    junit = blobs.put_bytes(b"junit")
    artifact = blobs.put_bytes(b"evidence artifact")
    orphan = blobs.put_bytes(b"orphan")
    with session_scope(engine) as s:
        inv = seed(s)
        attempt = service.start_attempt(s, inv, 3)
        run = ExecutionResult(attempt_id=attempt.id, run_index=0, junit_ref=junit)
        s.add(run)
        s.flush()
        s.add(EvidenceRecord(investigation_id=inv.id, kind="report", payload={},
                             execution_result_id=run.id, artifact_ref=artifact))

    with session_scope(engine) as s:
        assert sweep_blobs(s, blobs, {junit, artifact, orphan}) == 1
    assert blobs.path(junit).read_bytes() == b"junit"
    assert blobs.path(artifact).read_bytes() == b"evidence artifact"
    with pytest.raises(FileNotFoundError):
        blobs.path(orphan)


# --- M9.1 R5: migrations must also work on a database that already holds data ------------------
def _populate_at_0001(eng):
    import datetime as dt

    import sqlalchemy as sa

    meta = sa.MetaData()
    meta.reflect(eng)
    now = dt.datetime.now(dt.UTC)
    rows = [
        ("projects", dict(id="p1", name="p", created_at=now)),
        ("repositories", dict(id="r1", project_id="p1", source_type="archive", storage_ref="x",
                              created_at=now)),
        ("bug_reports", dict(id="b1", project_id="p1", title="t", description="",
                             missing_fields=[], created_at=now)),
        ("investigations", dict(id="i1", bug_report_id="b1", repository_id="r1",
                                state="COMPLETED", created_at=now, updated_at=now)),
        ("investigation_events", dict(investigation_id="i1", to_state="CREATED", message="m",
                                      created_at=now)),
        ("attempts", dict(id="a1", investigation_id="i1", number=1, status="valid",
                          created_at=now)),
    ]
    with eng.begin() as conn:
        for table, values in rows:
            conn.execute(meta.tables[table].insert().values(**values))


def test_migration_0002_upgrades_and_downgrades_a_populated_database(tmp_path):
    import sqlalchemy as sa

    eng = make_engine(f"sqlite:///{(tmp_path / 'populated.db').as_posix()}")  # foreign keys ON
    cfg = Config("alembic.ini")
    cfg.attributes["engine"] = eng
    command.upgrade(cfg, "0001")
    _populate_at_0001(eng)
    counts = {}
    for target, step in (("0002", command.upgrade), ("0001", command.downgrade),
                         ("0002", command.upgrade)):
        step(cfg, target)  # used to fail: DROP TABLE investigations violated child foreign keys
        with eng.connect() as conn:
            counts[target] = [conn.execute(sa.text(f"select count(*) from {t}")).scalar()
                              for t in ("investigations", "investigation_events", "attempts")]
            assert conn.execute(sa.text("PRAGMA foreign_keys")).scalar() == 1  # restored
            assert conn.execute(sa.text("PRAGMA foreign_key_check")).fetchall() == []
        assert counts[target] == [1, 1, 1]
    eng.dispose()
