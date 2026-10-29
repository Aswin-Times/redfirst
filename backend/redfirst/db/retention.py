"""Deleting investigations and the stored logs they own.

Only finished investigations (COMPLETED / FAILED / CANCELLED) are ever deleted. Blobs are
content-addressed and may be shared, so a blob is removed only when nothing references it.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, delete, or_, select
from sqlalchemy.orm import Session

from redfirst.db.models import (
    Attempt,
    BugReport,
    EvidenceRecord,
    ExecutionResult,
    GeneratedTest,
    Investigation,
    InvestigationEvent,
    Repository,
)
from redfirst.db.session import session_scope
from redfirst.domain.state_machine import is_terminal
from redfirst.storage.blobs import BlobStore

log = logging.getLogger(__name__)


class NotFinished(ValueError):
    """The investigation is still running; cancel it before deleting."""


def delete_investigation(s: Session, inv: Investigation) -> set[str]:
    """Delete one finished investigation and its rows. Returns candidate blob keys."""
    if not is_terminal(inv.state):
        raise NotFinished(f"investigation is {inv.state.value}")
    attempt_ids = list(s.scalars(select(Attempt.id).where(Attempt.investigation_id == inv.id)))
    refs: set[str] = set()
    if attempt_ids:
        for row in s.execute(select(ExecutionResult.stdout_ref, ExecutionResult.stderr_ref)
                             .where(ExecutionResult.attempt_id.in_(attempt_ids))):
            refs.update(r for r in row if r)
        s.execute(delete(ExecutionResult).where(ExecutionResult.attempt_id.in_(attempt_ids)))
        s.execute(delete(GeneratedTest).where(GeneratedTest.attempt_id.in_(attempt_ids)))
    s.execute(delete(EvidenceRecord).where(EvidenceRecord.investigation_id == inv.id))
    s.execute(delete(Attempt).where(Attempt.investigation_id == inv.id))
    s.execute(delete(InvestigationEvent).where(InvestigationEvent.investigation_id == inv.id))
    report_id = inv.bug_report_id
    s.execute(delete(Investigation).where(Investigation.id == inv.id))
    s.flush()
    if not s.scalar(select(Investigation.id).where(Investigation.bug_report_id == report_id)
                    .limit(1)):
        s.execute(delete(BugReport).where(BugReport.id == report_id))
    return refs


def sweep_blobs(s: Session, blobs: BlobStore, candidates: set[str]) -> int:
    """Remove candidate blobs that no execution log or repository still references."""
    removed = 0
    for key in candidates:
        in_use = s.scalar(
            select(ExecutionResult.id).where(
                or_(ExecutionResult.stdout_ref == key, ExecutionResult.stderr_ref == key)
            ).limit(1)
        ) or s.scalar(select(Repository.id).where(Repository.storage_ref == key).limit(1))
        if not in_use and blobs.delete(key):
            removed += 1
    return removed


def purge_older_than(engine: Engine, blobs: BlobStore, days: int) -> dict[str, int]:
    """Delete finished investigations created more than ``days`` ago."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    deleted, candidates = 0, set()
    with session_scope(engine) as s:
        old = s.scalars(select(Investigation).where(Investigation.created_at < cutoff)).all()
        for inv in old:
            if is_terminal(inv.state):
                candidates |= delete_investigation(s, inv)
                deleted += 1
    with session_scope(engine) as s:
        removed = sweep_blobs(s, blobs, candidates)
    log.info("retention: deleted %d investigations, %d blobs", deleted, removed)
    return {"investigations": deleted, "blobs": removed}


def main() -> None:
    from redfirst.core.config import get_settings
    from redfirst.db.session import make_engine

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    result = purge_older_than(make_engine(), BlobStore(settings.data_dir / "blobs"),
                              settings.retention_days)
    print(result)


if __name__ == "__main__":
    main()
