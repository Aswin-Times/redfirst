"""Engine and session helpers."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from redfirst.core.config import get_settings


def make_engine(url: str | None = None) -> Engine:
    engine = create_engine(url or get_settings().database_url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":  # enforce FKs in tests, as Postgres does
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Commit on success, roll back and re-raise on any error."""
    session = sessionmaker(engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
