"""Database engine, session and declarative base.

PostgreSQL is the system of record (TSD §50). Each domain owns a Postgres schema so boundaries are
visible in the database as well as in code.
"""

import os
import secrets
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, create_engine, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from weza.config import get_settings

DOMAIN_SCHEMAS = [
    "identity", "customer", "need", "institution", "product", "appetite", "matching", "consent",
    "opportunity", "notification", "commercial", "integrity", "trust", "platform", "admin", "analytics",
]

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def uuid7() -> uuid.UUID:
    """Time-ordered UUID (RFC 9562 v7) — index-friendly primary keys."""
    ms = int(time.time() * 1000)
    rand = int.from_bytes(secrets.token_bytes(10), "big")
    value = (ms & 0xFFFFFFFFFFFF) << 80
    value |= 0x7 << 76
    value |= ((rand >> 68) & 0x0FFF) << 64
    value |= 0b10 << 62
    value |= rand & 0x3FFFFFFFFFFFFFFF
    return uuid.UUID(int=value)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = os.environ.get("WEZA_TEST_DATABASE_URL") or get_settings().sqlalchemy_url
        _engine = create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10, future=True)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=True, expire_on_commit=False)
    return _engine


def reset_engine(url: str | None = None) -> None:
    """Used by tests to point the app at a disposable database."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    if url:
        os.environ["WEZA_TEST_DATABASE_URL"] = url
    get_engine()


def SessionLocal() -> Session:  # noqa: N802 — factory reads like a class
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one transaction per request, committed only on success."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
