from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _db_url() -> str:
    path = get_settings().app_db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


engine = create_engine(_db_url(), connect_args={"check_same_thread": False}, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

