"""Job claiming and crash recovery, using the investigations table as the queue.

Claiming is a compare-and-swap from CREATED that records the worker id and a lease; it is safe
with several workers on both SQLite and PostgreSQL because only one UPDATE can match. On
PostgreSQL ``FOR UPDATE SKIP LOCKED`` additionally lets workers skip rows another worker is
claiming instead of waiting; SQLite ignores the clause and serialises writers instead.

Recovery fails only runs whose lease has expired, so starting a worker never touches runs that
a live worker is still heartbeating. Runs are not resumed: a partial sandbox run cannot be
trusted, so the history is kept and the run is closed as retryable.
"""

import os
import socket
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, select

from redfirst.db import service
from redfirst.db.models import Investigation
from redfirst.db.session import session_scope
from redfirst.domain.enums import InvestigationState as S

DEFAULT_LEASE_SECONDS = 120.0
_CLAIM_RACES = 5  # how many times to move on to the next row after losing a race


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def claim_next(engine: Engine, worker_id: str | None = None,
               lease_seconds: float = DEFAULT_LEASE_SECONDS) -> str | None:
    """Claim the oldest queued investigation for ``worker_id``; None if the queue is empty."""
    worker_id = worker_id or default_worker_id()
    for _ in range(_CLAIM_RACES):
        with session_scope(engine) as s:
            inv_id = s.scalar(
                select(Investigation.id).where(Investigation.state == S.CREATED)
                .order_by(Investigation.created_at).limit(1)
                .with_for_update(skip_locked=True)
            )
            if inv_id is None:
                return None
            until = datetime.now(UTC) + timedelta(seconds=lease_seconds)
            if service.claim(s, inv_id, worker_id, until):
                return inv_id
    return None  # kept losing races; the caller simply polls again


def recover_lost(engine: Engine, now: datetime | None = None) -> list[str]:
    """Fail in-progress investigations whose worker lease expired. Safe to call any time."""
    with session_scope(engine) as s:
        return service.recover_expired(s, now or datetime.now(UTC))
