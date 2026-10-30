"""Persistence operations that enforce the investigation state machine.

State changes are compare-and-swap updates (``UPDATE ... WHERE state = :expected``): a writer
acting on a stale read (for example a worker that has not seen a user's cancel) gets
``StaleState`` instead of silently overwriting the newer state. This holds on SQLite and
PostgreSQL because it relies only on the atomicity of a single UPDATE.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from redfirst.db.models import Attempt, Investigation, InvestigationEvent
from redfirst.domain.enums import InvestigationState as S
from redfirst.domain.enums import Outcome, OutcomeReason
from redfirst.domain.state_machine import (
    TERMINAL_STATES,
    InvalidTransition,
    ensure_transition,
    is_terminal,
)

_OUTCOME_FOR_FAILED = (Outcome.EXECUTION_ERROR, OutcomeReason.RUNNER_FAILURE)
_TERMINAL = sorted(TERMINAL_STATES)
_NOT_RUNNING = [*_TERMINAL, S.CREATED]


class StaleState(RuntimeError):
    """The investigation changed since it was read; re-read it and decide again."""


def create_investigation(session: Session, bug_report_id: str, repository_id: str) -> Investigation:
    inv = Investigation(bug_report_id=bug_report_id, repository_id=repository_id)
    session.add(inv)
    session.flush()
    session.add(InvestigationEvent(investigation_id=inv.id, from_state=None, to_state=S.CREATED,
                                   message="investigation created"))
    session.flush()
    return inv


def transition(
    session: Session,
    inv: Investigation,
    target: S,
    message: str = "",
    data: dict[str, Any] | None = None,
) -> None:
    """Move to ``target`` if the state machine allows it, recording an event atomically.

    The move only happens if the row is still in the state ``inv`` was read in; otherwise
    ``StaleState`` is raised and nothing (not even the event) is written.
    """
    current = inv.state
    ensure_transition(current, target)
    now = datetime.now(UTC)
    values: dict[str, Any] = {"state": target, "updated_at": now}
    if is_terminal(target):
        values["completed_at"] = now
    result = session.execute(
        update(Investigation)
        .where(Investigation.id == inv.id, Investigation.state == current)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise StaleState(f"investigation {inv.id} is no longer {current.value}")
    for key, value in values.items():  # reflect the committed row without another UPDATE
        set_committed_value(inv, key, value)
    session.add(InvestigationEvent(investigation_id=inv.id, from_state=current, to_state=target,
                                   message=message, data=data))
    session.flush()


def cancel(session: Session, inv: Investigation, message: str = "cancelled by user",
           attempts: int = 3) -> None:
    """Cancel from whatever non-terminal state the row is in now, re-reading if it moved."""
    for _ in range(attempts):
        if is_terminal(inv.state):
            raise InvalidTransition(f"investigation already {inv.state.value}")
        try:
            transition(session, inv, S.CANCELLED, message)
            return
        except StaleState:
            session.refresh(inv)
    raise StaleState(f"investigation {inv.id} kept changing; try again")


def claim(session: Session, inv_id: str, worker_id: str, lease_until: datetime) -> bool:
    """Take ownership of a queued investigation. False if another worker got it first."""
    result = session.execute(
        update(Investigation)
        .where(Investigation.id == inv_id, Investigation.state == S.CREATED)
        .values(state=S.ANALYZING_REPORT, worker_id=worker_id, lease_expires_at=lease_until,
                updated_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return False
    session.add(InvestigationEvent(
        investigation_id=inv_id, from_state=S.CREATED, to_state=S.ANALYZING_REPORT,
        message=f"claimed by worker {worker_id}",
        data={"worker_id": worker_id, "lease_expires_at": lease_until.isoformat()}))
    session.flush()
    return True


def renew_lease(session: Session, inv_id: str, worker_id: str, lease_until: datetime) -> bool:
    """Heartbeat. False once the run is finished, recovered, or owned by someone else."""
    result = session.execute(
        update(Investigation)
        .where(Investigation.id == inv_id, Investigation.worker_id == worker_id,
               Investigation.state.not_in(_TERMINAL))
        .values(lease_expires_at=lease_until)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def recover_expired(session: Session, now: datetime) -> list[str]:
    """Fail in-progress runs whose owner's lease has expired (or that never had one).

    Each row is failed with a compare-and-swap that re-checks the state and lease, so a
    heartbeat or transition that lands concurrently wins and the run is left alone.
    """
    expired = or_(Investigation.lease_expires_at.is_(None), Investigation.lease_expires_at < now)
    rows = session.execute(
        select(Investigation.id, Investigation.state, Investigation.worker_id)
        .where(Investigation.state.not_in(_NOT_RUNNING), expired)
        .order_by(Investigation.created_at)
    ).all()
    recovered: list[str] = []
    for inv_id, state, worker_id in rows:
        error = {"type": "WorkerLost", "detail": f"worker lease expired during {state.value}",
                 "worker_id": worker_id, "retryable": True}
        result = session.execute(
            update(Investigation)
            .where(Investigation.id == inv_id, Investigation.state == state, expired)
            .values(state=S.FAILED, outcome=_OUTCOME_FOR_FAILED[0],
                    outcome_reason=_OUTCOME_FOR_FAILED[1], error=error,
                    completed_at=now, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            session.add(InvestigationEvent(
                investigation_id=inv_id, from_state=state, to_state=S.FAILED,
                message="worker stopped before the investigation finished (lease expired)",
                data={"error": error}))
            recovered.append(inv_id)
    session.flush()
    return recovered


def complete(
    session: Session, inv: Investigation, outcome: Outcome, reason: OutcomeReason,
    message: str = "",
) -> None:
    """Finish with a verified outcome (from the verifier, never from the LLM)."""
    if outcome is Outcome.EXECUTION_ERROR:
        raise ValueError("EXECUTION_ERROR results use fail(), which records the error details")
    transition(session, inv, S.COMPLETED, message or f"{outcome.value}: {reason.value}",
               {"outcome": outcome.value, "reason": reason.value})
    inv.outcome, inv.outcome_reason = outcome, reason


def fail(session: Session, inv: Investigation, error: dict[str, Any], message: str = "") -> None:
    """Infrastructure failure: terminal FAILED with outcome EXECUTION_ERROR."""
    transition(session, inv, S.FAILED, message or "infrastructure failure", {"error": error})
    inv.outcome, inv.outcome_reason = _OUTCOME_FOR_FAILED
    inv.error = error


def start_attempt(session: Session, inv: Investigation, max_attempts: int) -> Attempt:
    """Create the next attempt, refusing to exceed the configured bound."""
    count = len(inv.attempts)
    if count >= max_attempts:
        raise ValueError(f"attempt limit reached ({max_attempts})")
    attempt = Attempt(investigation_id=inv.id, number=count + 1)
    session.add(attempt)
    session.flush()
    session.refresh(inv, ["attempts"])
    return attempt


def find_unfinished(session: Session) -> list[Investigation]:
    """Investigations not yet in a terminal state (queued or running)."""
    return list(session.scalars(
        select(Investigation).where(Investigation.state.not_in(_TERMINAL))
        .order_by(Investigation.created_at)
    ))
