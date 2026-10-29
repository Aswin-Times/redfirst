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
