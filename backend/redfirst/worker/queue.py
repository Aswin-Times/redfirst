"""Job claiming and restart recovery, using the investigations table as the queue.

On PostgreSQL ``FOR UPDATE SKIP LOCKED`` lets several workers claim safely. SQLite ignores
the lock clause, so only one worker should run against SQLite.
"""

from sqlalchemy import Engine, select

from redfirst.db import service
from redfirst.db.models import Investigation
from redfirst.db.session import session_scope
from redfirst.domain.enums import InvestigationState as S


def claim_next(engine: Engine) -> str | None:
    """Atomically move the oldest CREATED investigation to ANALYZING_REPORT."""
    with session_scope(engine) as s:
        inv = s.scalars(
            select(Investigation).where(Investigation.state == S.CREATED)
            .order_by(Investigation.created_at).limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if inv is None:
            return None
        service.transition(s, inv, S.ANALYZING_REPORT, "claimed by worker")
        return inv.id


def recover_lost(engine: Engine) -> list[str]:
    """Mark investigations a dead worker left mid-pipeline as FAILED (worker_lost).

    Call only when no other worker is running. Resuming mid-stage is not attempted:
    a partial sandbox run cannot be trusted, so the history is kept and the run is closed.
    """
    lost: list[str] = []
    with session_scope(engine) as s:
        for inv in service.find_unfinished(s):
            if inv.state is S.CREATED:
                continue
            service.fail(s, inv, {"type": "WorkerLost", "detail": f"stopped in {inv.state.value}"},
                         "worker stopped before the investigation finished")
            lost.append(inv.id)
    return lost
