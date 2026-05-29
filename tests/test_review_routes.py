from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db import Base
from app.batches import create_batch
from app.models import Case, CaseMatch, Channel, Message
from app.telegram.normalizer import normalize_text, text_sha256
from app.web.main import app
from app.web.routes import db_session


@pytest.fixture()
def review_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as session:
        yield session
    app.dependency_overrides.clear()


def _add_match(session, status: str, text: str = "text", batch_id: int | None = None) -> CaseMatch:
    suffix = abs(hash((status, text, batch_id))) % 100000
    channel = Channel(username=f"chan_{status}_{suffix}", title=f"Channel {status}")
    session.add(channel)
    session.flush()
    case = Case(batch_id=batch_id, raw_text=f"case {status}", place_name="Краматорск")
    session.add(case)
    session.flush()
    norm = normalize_text(text)
    message = Message(
        channel_id=channel.id,
        tg_message_id=suffix,
        posted_at=datetime(2026, 5, 29, 7, 0),
        collected_at=datetime(2026, 5, 29, 7, 0),
        text=text,
        normalized_text=norm,
        text_hash=text_sha256(norm),
        url=f"https://t.me/{channel.username}/1",
    )
    session.add(message)
    session.flush()
    match = CaseMatch(
        case_id=case.id,
        message_id=message.id,
        match_type="telegram",
        priority="B",
        total_score=0.7,
        explanation="match",
        review_status=status,
    )
    session.add(match)
    session.flush()
    return match


def _client(session):
    def override():
        yield session

    app.dependency_overrides.clear()
    app.dependency_overrides[db_session] = override
    client = TestClient(app)
    client.cookies.set("session", "dummy")
    return client


def test_review_default_pending(monkeypatch, review_session):
    from app.web import routes

    monkeypatch.setattr(routes, "require_login", lambda request: None)
    _add_match(review_session, "pending", "pending visible")
    _add_match(review_session, "approved", "approved hidden")
    response = _client(review_session).get("/review")
    assert response.status_code == 200
    assert "pending visible" in response.text
    assert "approved hidden" not in response.text


def test_review_status_approved_filter(monkeypatch, review_session):
    from app.web import routes

    monkeypatch.setattr(routes, "require_login", lambda request: None)
    _add_match(review_session, "pending", "pending hidden")
    _add_match(review_session, "approved", "approved visible")
    response = _client(review_session).get("/review?status=approved")
    assert response.status_code == 200
    assert "approved visible" in response.text
    assert "pending hidden" not in response.text


def test_review_approve_ajax_returns_json_and_changes_status(monkeypatch, review_session):
    from app.web import routes

    monkeypatch.setattr(routes, "require_login", lambda request: None)
    monkeypatch.setattr(routes, "ensure_csrf", lambda request, token: None)
    match = _add_match(review_session, "pending")
    response = _client(review_session).post(
        f"/review/matches/{match.id}/approve",
        data={"csrf_token": "x"},
        headers={"X-Requested-With": "fetch", "Accept": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["review_status"] == "approved"
    assert review_session.get(CaseMatch, match.id).review_status == "approved"


def test_review_pending_count_decreases_after_approve(monkeypatch, review_session):
    from app.web import routes

    monkeypatch.setattr(routes, "require_login", lambda request: None)
    monkeypatch.setattr(routes, "ensure_csrf", lambda request, token: None)
    match = _add_match(review_session, "pending")
    client = _client(review_session)
    before = client.get("/review").text
    assert "Pending (<span data-count=\"pending\">1</span>)" in before
    client.post(
        f"/review/matches/{match.id}/approve",
        data={"csrf_token": "x"},
        headers={"X-Requested-With": "fetch", "Accept": "application/json"},
    )
    after = client.get("/review").text
    assert "Pending (<span data-count=\"pending\">0</span>)" in after


def test_review_default_current_batch_only_and_old_batch_query(monkeypatch, review_session):
    from app.web import routes

    monkeypatch.setattr(routes, "require_login", lambda request: None)
    old = create_batch(review_session, source_filename="old.docx")
    current = create_batch(review_session, source_filename="current.docx")
    _add_match(review_session, "pending", "old batch pending", batch_id=old.id)
    _add_match(review_session, "pending", "current batch pending", batch_id=current.id)
    client = _client(review_session)
    response = client.get("/review")
    assert "current batch pending" in response.text
    assert "old batch pending" not in response.text
    response = client.get(f"/review?batch_id={old.id}")
    assert "old batch pending" in response.text
    assert "current batch pending" not in response.text
