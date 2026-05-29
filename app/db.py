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
    with engine.begin() as connection:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_cases_batch_id ON cases(batch_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_exports_batch_id ON exports(batch_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_batch_id ON jobs(batch_id)"))
    _ensure_legacy_batch()


def _ensure_runtime_columns() -> None:
    required = {
        "cases": {
            "batch_id": "INTEGER REFERENCES case_batches(id)",
            "oblast": "VARCHAR",
            "reference_text": "TEXT",
            "raw_grid_northing": "VARCHAR",
            "raw_grid_easting": "VARCHAR",
            "coordinate_source": "VARCHAR",
            "parser_warnings": "TEXT",
        },
        "jobs": {
            "batch_id": "INTEGER REFERENCES case_batches(id)",
            "params_json": "TEXT",
        },
        "exports": {
            "batch_id": "INTEGER REFERENCES case_batches(id)",
        },
        "evidence_files": {
            "batch_id": "INTEGER REFERENCES case_batches(id)",
        },
        "firms_points": {
            "batch_id": "INTEGER REFERENCES case_batches(id)",
        },
        "case_matches": {
            "review_status": "VARCHAR DEFAULT 'pending'",
            "review_note": "TEXT",
            "score_details_json": "TEXT",
            "reject_reason": "TEXT",
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


def _ensure_legacy_batch() -> None:
    inspector = inspect(engine)
    if "case_batches" not in inspector.get_table_names() or "cases" not in inspector.get_table_names():
        return
    with engine.begin() as connection:
        unassigned = connection.execute(text("SELECT COUNT(*) FROM cases WHERE batch_id IS NULL")).scalar() or 0
        if not unassigned:
            return
        existing = connection.execute(text("SELECT id FROM case_batches WHERE source_filename = 'legacy' ORDER BY id LIMIT 1")).scalar()
        if existing:
            batch_id = existing
        else:
            result = connection.execute(
                text(
                    "INSERT INTO case_batches (created_at, updated_at, source_filename, title, status, night_mode, cases_count, matches_count, approved_count, pending_count) "
                    "VALUES (CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'legacy', 'Legacy imported cases', 'active', 0, 0, 0, 0, 0)"
                )
            )
            batch_id = result.lastrowid
        connection.execute(text("UPDATE cases SET batch_id = :batch_id WHERE batch_id IS NULL"), {"batch_id": batch_id})
