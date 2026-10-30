"""D4 (stale state transitions) and D5 (worker ownership and recovery) on SQLite.

Concurrent writers are simulated deterministically with separate sessions; one test also uses
threads. These tests run on SQLite only. PostgreSQL behaviour (row locks with SKIP LOCKED) is
NOT exercised here; see README "Workers and concurrency".
"""

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from redfirst.db import service
from redfirst.db.models import (
    Base,
    BugReport,
    Investigation,
    InvestigationEvent,
    Project,
    Repository,
)
from redfirst.db.session import make_engine, session_scope
from redfirst.domain.enums import InvestigationState as S
from redfirst.worker.__main__ import run_one
from redfirst.worker.lease import LeaseKeeper
from redfirst.worker.orchestrator import Orchestrator
from redfirst.worker.queue import claim_next, recover_lost
from tests.integration.test_pipeline_e2e import (  # noqa: F401  (make_env is a fixture)
    EXCEPTION,
    make_env,
    seed,
)

PIPELINE = [S.ANALYZING_REPORT, S.ANALYZING_REPOSITORY, S.GENERATING_TEST, S.VALIDATING_TEST,
            S.EXECUTING_TEST]


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'concurrency.db'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def new_investigation(engine) -> str:
    with session_scope(engine) as s:
        project = Project(name=f"p-{uuid.uuid4().hex}")
        s.add(project)
        s.flush()
        report = BugReport(project_id=project.id, title="t")
        repo = Repository(project_id=project.id, source_type="archive", storage_ref="x")
        s.add_all([report, repo])
        s.flush()
        return service.create_investigation(s, report.id, repo.id).id


def at_executing(engine) -> str:
    inv_id = new_investigation(engine)
    with session_scope(engine) as s:
        inv = s.get(Investigation, inv_id)
        for state in PIPELINE:
            service.transition(s, inv, state)
    return inv_id


def state_of(engine, inv_id) -> S:
    with session_scope(engine) as s:
        return s.get(Investigation, inv_id).state


def try_transition(session, inv, target) -> Exception | None:
    try:
        service.transition(session, inv, target)
        session.commit()
        return None
    except Exception as exc:  # noqa: BLE001 - the test inspects the type
        session.rollback()
        return exc


# --- D4: a stale read must never overwrite a newer state ----------------------------------------
def test_worker_cannot_overwrite_a_cancellation_from_a_stale_read(engine):
    inv_id = at_executing(engine)
    worker = sessionmaker(engine)()
    stale = worker.get(Investigation, inv_id)          # worker reads EXECUTING_TEST
    with session_scope(engine) as api:                  # user cancels in the meantime
        service.transition(api, api.get(Investigation, inv_id), S.CANCELLED, "user")
    error = try_transition(worker, stale, S.VERIFYING_RESULT)
    worker.close()
    assert state_of(engine, inv_id) is S.CANCELLED
    assert isinstance(error, service.StaleState)


def test_rejected_transition_writes_no_event(engine):
    inv_id = at_executing(engine)
    worker = sessionmaker(engine)()
    stale = worker.get(Investigation, inv_id)
    with session_scope(engine) as api:
        service.transition(api, api.get(Investigation, inv_id), S.CANCELLED, "user")
    try_transition(worker, stale, S.VERIFYING_RESULT)
    worker.close()
    with session_scope(engine) as s:
        events = s.scalars(select(InvestigationEvent).where(
            InvestigationEvent.investigation_id == inv_id).order_by(InvestigationEvent.id)).all()
        assert events[-1].to_state is S.CANCELLED
        assert S.VERIFYING_RESULT not in [e.to_state for e in events]


def test_competing_transitions_only_the_first_wins(engine):
    inv_id = at_executing(engine)
    a, b = sessionmaker(engine)(), sessionmaker(engine)()
    inv_a, inv_b = a.get(Investigation, inv_id), b.get(Investigation, inv_id)  # both see EXECUTING
    assert try_transition(a, inv_a, S.VERIFYING_RESULT) is None
    assert isinstance(try_transition(b, inv_b, S.FAILED), service.StaleState)
    a.close()
    b.close()
    assert state_of(engine, inv_id) is S.VERIFYING_RESULT


def test_terminal_state_cannot_be_overwritten_by_a_stale_session(engine):
    inv_id = at_executing(engine)
    stale_session = sessionmaker(engine)()
    stale = stale_session.get(Investigation, inv_id)
    with session_scope(engine) as s:
        inv = s.get(Investigation, inv_id)
        service.transition(s, inv, S.VERIFYING_RESULT)
        service.transition(s, inv, S.COMPLETED)
    assert isinstance(try_transition(stale_session, stale, S.VERIFYING_RESULT), service.StaleState)
    stale_session.close()
    assert state_of(engine, inv_id) is S.COMPLETED


def test_valid_transitions_still_work_and_update_the_loaded_object(engine):
    inv_id = new_investigation(engine)
    with session_scope(engine) as s:
        inv = s.get(Investigation, inv_id)
        service.transition(s, inv, S.ANALYZING_REPORT)
        assert inv.state is S.ANALYZING_REPORT
        service.transition(s, inv, S.CANCELLED)
        assert inv.state is S.CANCELLED and inv.completed_at is not None
    assert state_of(engine, inv_id) is S.CANCELLED


def test_cancel_retries_when_the_worker_moved_on(engine):
    inv_id = at_executing(engine)
    api = sessionmaker(engine)()
    stale = api.get(Investigation, inv_id)              # API reads EXECUTING_TEST
    with session_scope(engine) as worker:               # worker advances
        service.transition(worker, worker.get(Investigation, inv_id), S.VERIFYING_RESULT)
    service.cancel(api, stale, "user")                   # still succeeds, from the new state
    api.commit()
    api.close()
    assert state_of(engine, inv_id) is S.CANCELLED


def test_orchestrator_stops_instead_of_overwriting_a_concurrent_cancel(make_env, monkeypatch,  # noqa: F811
                                                                       tmp_path):
    """A cancel lands between the worker's read and its write (injected deterministically)."""
    env = make_env([EXCEPTION])
    inv_id = seed(env, "exception_bug", tmp_path)
    claim_next(env.deps.engine)

    real = service.ensure_transition
    fired = []

    def cancel_just_before_verifying(current, target):
        if target is S.VERIFYING_RESULT and not fired:
            fired.append(True)
            with session_scope(env.deps.engine) as api:
                service.transition(api, api.get(Investigation, inv_id), S.CANCELLED, "user")
        return real(current, target)

    monkeypatch.setattr(service, "ensure_transition", cancel_just_before_verifying)
    Orchestrator(env.deps, inv_id).run()
    assert fired
    with session_scope(env.deps.engine) as s:
        inv = s.get(Investigation, inv_id)
        assert inv.state is S.CANCELLED and inv.outcome is None


# --- D5: ownership by lease; recovery only of expired leases --------------------------------------
def test_starting_another_worker_does_not_fail_a_live_run(engine):
    inv_id = new_investigation(engine)
    assert claim_next(engine) == inv_id                  # worker A is running it
    assert recover_lost(engine) == []                    # worker B starts up
    assert state_of(engine, inv_id) is S.ANALYZING_REPORT


def test_claim_records_owner_and_lease(engine):
    inv_id = new_investigation(engine)
    before = datetime.now(UTC)
    assert claim_next(engine, worker_id="worker-a", lease_seconds=60) == inv_id
    with session_scope(engine) as s:
        inv = s.get(Investigation, inv_id)
        assert inv.worker_id == "worker-a"
        assert _aware(inv.lease_expires_at) >= before + timedelta(seconds=59)
        claimed = s.scalars(select(InvestigationEvent).where(
            InvestigationEvent.investigation_id == inv_id,
            InvestigationEvent.to_state == S.ANALYZING_REPORT)).one()
        assert "worker-a" in claimed.message


def test_expired_lease_is_recovered_and_names_the_lost_worker(engine):
    inv_id = new_investigation(engine)
    claim_next(engine, worker_id="worker-a", lease_seconds=60)
    later = datetime.now(UTC) + timedelta(seconds=120)
    assert recover_lost(engine, now=later) == [inv_id]
    with session_scope(engine) as s:
        inv = s.get(Investigation, inv_id)
        assert inv.state is S.FAILED and inv.error["type"] == "WorkerLost"
        assert inv.error["worker_id"] == "worker-a" and inv.error["retryable"] is True


def test_renewed_lease_is_not_recovered(engine):
    inv_id = new_investigation(engine)
    claim_next(engine, worker_id="worker-a", lease_seconds=60)
    t90 = datetime.now(UTC) + timedelta(seconds=90)
    with session_scope(engine) as s:  # heartbeat at t+30 extends the lease to t+150
        assert service.renew_lease(s, inv_id, "worker-a",
                                   datetime.now(UTC) + timedelta(seconds=150))
    assert recover_lost(engine, now=t90) == []
    assert state_of(engine, inv_id) is S.ANALYZING_REPORT


def test_only_the_owner_can_renew_and_renewal_fails_after_recovery(engine):
    inv_id = new_investigation(engine)
    claim_next(engine, worker_id="worker-a", lease_seconds=60)
    with session_scope(engine) as s:
        assert not service.renew_lease(s, inv_id, "worker-b", datetime.now(UTC))
    recover_lost(engine, now=datetime.now(UTC) + timedelta(seconds=120))
    with session_scope(engine) as s:
        assert not service.renew_lease(s, inv_id, "worker-a",
                                       datetime.now(UTC) + timedelta(seconds=60))


def test_stalled_worker_cannot_write_after_its_run_was_recovered(engine):
    inv_id = new_investigation(engine)
    claim_next(engine, worker_id="worker-a", lease_seconds=60)
    stalled = sessionmaker(engine)()
    inv = stalled.get(Investigation, inv_id)             # worker A read ANALYZING_REPORT, froze
    recover_lost(engine, now=datetime.now(UTC) + timedelta(seconds=120))
    assert isinstance(try_transition(stalled, inv, S.ANALYZING_REPOSITORY), service.StaleState)
    stalled.close()
    assert state_of(engine, inv_id) is S.FAILED


def test_recovery_ignores_queued_and_finished_investigations_and_treats_no_lease_as_expired(
        engine):
    queued = new_investigation(engine)
    finished = new_investigation(engine)
    legacy = new_investigation(engine)
    with session_scope(engine) as s:
        service.transition(s, s.get(Investigation, finished), S.CANCELLED)
        # a run claimed by a pre-lease worker version: in progress, no lease recorded
        service.transition(s, s.get(Investigation, legacy), S.ANALYZING_REPORT)
    assert recover_lost(engine) == [legacy]
    assert state_of(engine, queued) is S.CREATED
    assert state_of(engine, finished) is S.CANCELLED


def test_two_workers_racing_for_the_same_row_only_one_claims_it(engine):
    inv_id = new_investigation(engine)
    with session_scope(engine) as a, session_scope(engine) as b:
        won_a = service.claim(a, inv_id, "worker-a", datetime.now(UTC) + timedelta(seconds=60))
        a.commit()
        won_b = service.claim(b, inv_id, "worker-b", datetime.now(UTC) + timedelta(seconds=60))
    assert (won_a, won_b) == (True, False)
    with session_scope(engine) as s:
        assert s.get(Investigation, inv_id).worker_id == "worker-a"


def test_concurrent_workers_claim_each_investigation_exactly_once(engine):
    ids = {new_investigation(engine) for _ in range(12)}
    claimed: list[tuple[str, str]] = []
    lock = threading.Lock()
    errors: list[BaseException] = []

    def work(name: str) -> None:
        try:
            while (inv_id := claim_next(engine, worker_id=name, lease_seconds=60)) is not None:
                with lock:
                    claimed.append((inv_id, name))
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(f"worker-{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    assert sorted(i for i, _ in claimed) == sorted(ids)  # every one claimed, none twice
    with session_scope(engine) as s:
        owners = {i.id: i.worker_id for i in s.scalars(select(Investigation))}
    assert all(owners[i] == w for i, w in claimed)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# --- heartbeat and the worker loop ---------------------------------------------------------------
def lease_of(engine, inv_id) -> datetime:
    with session_scope(engine) as s:
        return _aware(s.get(Investigation, inv_id).lease_expires_at)


def wait_for(predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_heartbeat_extends_the_lease_and_notices_when_the_run_is_taken_away(engine):
    inv_id = new_investigation(engine)
    claim_next(engine, worker_id="worker-a", lease_seconds=10)
    first = lease_of(engine, inv_id)
    with LeaseKeeper(engine, inv_id, "worker-a", lease_seconds=60, interval=0.05) as lease:
        assert wait_for(lambda: lease_of(engine, inv_id) > first + timedelta(seconds=30))
        assert not lease.lost.is_set()
        # the worker stalled long enough for another worker to recover the run
        recover_lost(engine, now=datetime.now(UTC) + timedelta(seconds=600))
        assert wait_for(lease.lost.is_set)
    assert state_of(engine, inv_id) is S.FAILED


def test_orchestrator_with_a_lost_lease_writes_no_further_state(make_env, tmp_path):  # noqa: F811
    env = make_env([EXCEPTION])
    inv_id = seed(env, "exception_bug", tmp_path)
    claim_next(env.deps.engine, worker_id="worker-a")
    lease = LeaseKeeper(env.deps.engine, inv_id, "worker-a", lease_seconds=60)  # not started
    lease.lost.set()
    Orchestrator(env.deps, inv_id, lease=lease).run()
    assert state_of(env.deps.engine, inv_id) is S.ANALYZING_REPORT  # left for recovery
    assert env.provider.requests == []


def test_worker_iteration_recovers_expired_runs_then_runs_the_next_one(make_env, tmp_path):  # noqa: F811
    env = make_env([EXCEPTION])
    abandoned = seed(env, "no_bug", tmp_path)
    claim_next(env.deps.engine, worker_id="crashed-worker", lease_seconds=-1)  # already expired
    queued = seed(env, "exception_bug", tmp_path)
    assert run_one(env.deps, env.deps.engine, "worker-b", lease_seconds=60) == queued
    with session_scope(env.deps.engine) as s:
        lost, done = s.get(Investigation, abandoned), s.get(Investigation, queued)
        assert lost.state is S.FAILED and lost.error["worker_id"] == "crashed-worker"
        assert done.state is S.COMPLETED and done.worker_id == "worker-b"
