from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _db_url() -> str:
    path = get_settings().app_db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


engine = create_engine(_db_url(), connect_args={"check_same_thread": False, "timeout": 30}, future=True)
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
    with engine.begin() as connection:
        connection.execute(text("PRAGMA journal_mode=WAL"))
        connection.execute(text("PRAGMA synchronous=NORMAL"))
        connection.execute(text("PRAGMA busy_timeout=30000"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_posted_at ON messages(posted_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_channel_posted_at ON messages(channel_id, posted_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_relevance_posted_at ON messages(relevance_score, posted_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_message_keywords_message_id ON message_keywords(message_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_message_places_message_id ON message_places(message_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_case_matches_case_id ON case_matches(case_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_case_matches_message_id ON case_matches(message_id)"))
    _ensure_runtime_columns()


def _ensure_runtime_columns() -> None:
    required = {
        "cases": {
            "oblast": "VARCHAR",
            "reference_text": "TEXT",
            "raw_grid_northing": "VARCHAR",
            "raw_grid_easting": "VARCHAR",
            "coordinate_source": "VARCHAR",
            "parser_warnings": "TEXT",
        },
        "jobs": {
            "params_json": "TEXT",
        },
    }
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name, columns in required.items():
            if table_name not in inspector.get_table_names():
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_type in columns.items():
                if column_name not in existing:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
