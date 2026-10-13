"""
VIAHIND Vision - Database engine, session factory and shared column types.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from config import BASE_DIR, settings


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """Stores timestamps as UTC and always returns timezone-aware UTC datetimes.

    SQLite has no timezone support, so values are normalised to naive UTC on the way in
    and re-tagged as UTC on the way out. Naive inputs are rejected to avoid ambiguity.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed; use timezone-aware UTC values.")
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: Optional[datetime], dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_sqlite_url(url: str) -> str:
    """Make relative SQLite paths relative to the backend directory and create the folder."""
    prefix = "sqlite:///"
    if url.startswith(prefix) and not url.startswith(prefix + "/") and ":memory:" not in url:
        path = (BASE_DIR / url[len(prefix):]).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return prefix + path.as_posix()
    return url


def make_engine(url: str) -> Engine:
    url = _resolve_sqlite_url(url)
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            if ":memory:" not in url:
                cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return engine
    return create_engine(url, pool_pre_ping=True)


engine: Engine = make_engine(settings.EFFECTIVE_DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def configure_engine(new_engine: Engine) -> None:
    """Point the session factory at another engine (used by tests)."""
    global engine
    engine = new_engine
    SessionLocal.configure(bind=new_engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background workers: commit on success, roll back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
