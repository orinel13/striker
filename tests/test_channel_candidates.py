from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db import Base
from app.models import Channel, ChannelCandidate, Message
from app.telegram.channel_discovery import approve_channel_candidate, dedupe_channel_candidates, extract_channel_usernames, record_candidates
from app.telegram.normalizer import normalize_text, text_sha256
from app.web.main import app
from app.web.routes import db_session


@pytest.fixture()
def web_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as session:
        yield session
    app.dependency_overrides.clear()


def _client(session):
    def override():
        yield session

    app.dependency_overrides.clear()
    app.dependency_overrides[db_session] = override
    client = TestClient(app)
    client.cookies.set("session", "dummy")
    return client


def _message(session, text: str, source_username: str = "source") -> Message:
    channel = session.query(Channel).filter(Channel.username == source_username).one_or_none()
    if not channel:
        channel = Channel(username=source_username, title="Source", status="active")
        session.add(channel)
        session.flush()
    norm = normalize_text(text)
    message = Message(
        channel_id=channel.id,
        tg_message_id=session.query(Message).count() + 1,
        posted_at=datetime(2026, 5, 29, 10, 0),
        collected_at=datetime(2026, 5, 29, 10, 0),
        text=text,
        normalized_text=norm,
        text_hash=text_sha256(norm),
        url=f"https://t.me/{source_username}/1",
    )
    session.add(message)
    session.flush()
    return message


def test_extract_channel_usernames_variants():
    text = "@abc_news https://t.me/def_news t.me/ghi_news https://t.me/jkl_news/123 https://t.me/share @helper_bot"
    found = extract_channel_usernames(text)
    assert {"abc_news", "def_news", "ghi_news", "jkl_news"}.issubset(found)
    assert "share" not in found
    assert "helper_bot" not in found


def test_record_candidate_upsert_no_duplicates(web_session):
    message = _message(web_session, "see @foo_news")
    assert record_candidates(web_session, message, 0.6) == 1
    assert record_candidates(web_session, message, 0.7) == 1
    rows = web_session.query(ChannelCandidate).filter(ChannelCandidate.username == "foo_news").all()
    assert len(rows) == 1
    assert rows[0].mentions_count == 2
    assert rows[0].thematic_score == 0.7


def test_approved_candidate_not_recreated_as_pending(web_session):
    web_session.add(ChannelCandidate(username="foo_news", status="approved", mentions_count=1))
    web_session.flush()
    record_candidates(web_session, _message(web_session, "@foo_news"), 0.8)
    rows = web_session.query(ChannelCandidate).filter(ChannelCandidate.username == "foo_news").all()
    assert len(rows) == 1
    assert rows[0].status == "approved"


def test_rejected_candidate_not_recreated_as_pending(web_session):
    web_session.add(ChannelCandidate(username="foo_news", status="rejected", mentions_count=1))
    web_session.flush()
    record_candidates(web_session, _message(web_session, "@foo_news"), 0.8)
    rows = web_session.query(ChannelCandidate).filter(ChannelCandidate.username == "foo_news").all()
    assert len(rows) == 1
    assert rows[0].status == "rejected"


def test_existing_active_channel_skips_pending_candidate(web_session):
    web_session.add(Channel(username="foo_news", status="active"))
    web_session.flush()
    record_candidates(web_session, _message(web_session, "@foo_news"), 0.8)
    assert web_session.query(ChannelCandidate).filter(ChannelCandidate.username == "foo_news").count() == 0


def test_candidate_approve_creates_or_activates_channel(web_session):
    web_session.add(ChannelCandidate(username="foo_news", status="pending", thematic_score=0.9, title="Foo"))
    web_session.flush()
    approve_channel_candidate(web_session, "foo_news")
    candidate = web_session.query(ChannelCandidate).filter(ChannelCandidate.username == "foo_news").one()
    channel = web_session.query(Channel).filter(Channel.username == "foo_news").one()
    assert candidate.status == "approved"
    assert channel.status == "active"
    assert channel.title == "Foo"


def test_channel_candidates_default_pending_only(monkeypatch, web_session):
    from app.web import routes

    monkeypatch.setattr(routes, "require_login", lambda request: None)
    web_session.add_all(
        [
            ChannelCandidate(username="pending_news", status="pending"),
            ChannelCandidate(username="approved_news", status="approved"),
        ]
    )
    web_session.commit()
    response = _client(web_session).get("/channel-candidates")
    assert response.status_code == 200
    assert "pending_news" in response.text
    assert "approved_news" not in response.text


def test_channel_candidate_ajax_status_change(monkeypatch, web_session):
    from app.web import routes

    monkeypatch.setattr(routes, "require_login", lambda request: None)
    monkeypatch.setattr(routes, "ensure_csrf", lambda request, token: None)
    candidate = ChannelCandidate(username="foo_news", status="pending")
    web_session.add(candidate)
    web_session.commit()
    response = _client(web_session).post(
        f"/channel-candidates/{candidate.id}/reject",
        data={"csrf_token": "x"},
        headers={"X-Requested-With": "fetch", "Accept": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert web_session.get(ChannelCandidate, candidate.id).status == "rejected"


def test_dedupe_channel_candidates_noop_on_unique_data(web_session):
    web_session.add(ChannelCandidate(username="foo_news", status="pending"))
    web_session.flush()
    assert dedupe_channel_candidates(web_session) == 0
    assert web_session.query(ChannelCandidate).count() == 1
