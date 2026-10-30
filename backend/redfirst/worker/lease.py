"""Heartbeat that keeps a worker's lease on the investigation it is running.

A background thread renews the lease every ``lease_seconds / 4``. If renewal is refused (the
run was cancelled, finished, or recovered by another worker after this one stalled), ``lost``
is set and the orchestrator stops at its next stage boundary. Transient database errors are
logged and retried; if they persist, the lease simply expires and recovery takes over.
"""

import logging
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine

from redfirst.db import service
from redfirst.db.session import session_scope

log = logging.getLogger(__name__)


class LeaseKeeper:
    def __init__(self, engine: Engine, inv_id: str, worker_id: str, lease_seconds: float,
                 interval: float | None = None) -> None:
        self.engine = engine
        self.inv_id = inv_id
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.interval = interval if interval is not None else lease_seconds / 4
        self.lost = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name=f"lease-{inv_id[:8]}",
                                        daemon=True)

    def __enter__(self) -> "LeaseKeeper":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=self.interval + 5)

    def renew(self) -> bool:
        until = datetime.now(UTC) + timedelta(seconds=self.lease_seconds)
        with session_scope(self.engine) as s:
            return service.renew_lease(s, self.inv_id, self.worker_id, until)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                if not self.renew():
                    log.warning("lease on %s lost by %s", self.inv_id, self.worker_id)
                    self.lost.set()
                    return
            except Exception:  # noqa: BLE001 - keep heartbeating; expiry handles persistent errors
                log.exception("lease renewal for %s failed; will retry", self.inv_id)
