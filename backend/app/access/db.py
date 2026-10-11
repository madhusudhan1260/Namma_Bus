"""Database engine/session for the Access module (PostgreSQL via psycopg 3)."""

from typing import Iterator, Optional

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, InterfaceError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def configure(database_url: Optional[str] = None) -> Engine:
    """(Re)configure the engine. Tests call this with the test database URL."""
    global _engine, _SessionLocal
    url = database_url or settings.database_url
    if not url:
        raise RuntimeError("ACCESS_DATABASE_URL is not set")
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10, connect_args={"connect_timeout": 5})
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def engine() -> Engine:
    if _engine is None:
        configure()
    return _engine  # type: ignore[return-value]


def get_db() -> Iterator[Session]:
    """FastAPI dependency. A database outage becomes a clean 503 instead of a crash or a wrong answer.

    Always declared as Depends(get_db, scope="function"): the commit then happens BEFORE the response is sent,
    so a client that acts on a response immediately (e.g. create ticket → pay) always finds the committed data."""
    if _SessionLocal is None:
        configure()
    db: Session = _SessionLocal()  # type: ignore[misc]
    try:
        yield db
        db.commit()
    except (OperationalError, InterfaceError):
        db.rollback()
        raise HTTPException(status_code=503, detail="Service temporarily unavailable (database). Please try again shortly.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
