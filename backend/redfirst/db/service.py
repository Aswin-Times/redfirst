"""Persistence operations that enforce the investigation state machine."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from redfirst.db.models import Attempt, Investigation, InvestigationEvent
from redfirst.domain.enums import InvestigationState as S
from redfirst.domain.enums import Outcome, OutcomeReason
from redfirst.domain.state_machine import ensure_transition, is_terminal

_OUTCOME_FOR_FAILED = (Outcome.EXECUTION_ERROR, OutcomeReason.RUNNER_FAILURE)


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
    """Move to ``target`` if the state machine allows it, recording an event atomically."""
    ensure_transition(inv.state, target)
    session.add(InvestigationEvent(investigation_id=inv.id, from_state=inv.state, to_state=target,
                                   message=message, data=data))
    inv.state = target
    if is_terminal(target):
        inv.completed_at = datetime.now(UTC)
    session.flush()


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
    """Investigations a restarted worker must resume or mark as lost."""
    terminal = [S.COMPLETED, S.FAILED, S.CANCELLED]
    return list(session.scalars(
        select(Investigation).where(Investigation.state.not_in(terminal))
        .order_by(Investigation.created_at)
    ))
