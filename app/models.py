from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class Channel(Base):
    __tablename__ = "channels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String, unique=True)
    title: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)
    thematic_score: Mapped[float] = mapped_column(Float, default=0)
    last_message_id: Mapped[int] = mapped_column(Integer, default=0)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    messages = relationship("Message", back_populates="channel")


class ChannelCandidate(Base):
    __tablename__ = "channel_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str | None] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)
    source_channel_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("channels.id"))
    first_seen_message_id: Mapped[int | None] = mapped_column(Integer)
    mentions_count: Mapped[int] = mapped_column(Integer, default=1)
    thematic_score: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("channel_id", "tg_message_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(Integer, ForeignKey("channels.id"), nullable=False)
    tg_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    text_hash: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)
    has_media: Mapped[bool] = mapped_column(Boolean, default=False)
    media_path: Mapped[str | None] = mapped_column(String)
    fwd_from_name: Mapped[str | None] = mapped_column(String)
    fwd_from_channel: Mapped[str | None] = mapped_column(String)
    fwd_from_message_id: Mapped[int | None] = mapped_column(Integer)
    reply_to_message_id: Mapped[int | None] = mapped_column(Integer)
    raw_json: Mapped[str | None] = mapped_column(Text)
    canonical_message_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("messages.id"))
    relevance_score: Mapped[float] = mapped_column(Float, default=0)
    channel = relationship("Channel", back_populates="messages")


class MessageKeyword(Base):
    __tablename__ = "message_keywords"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(Integer, ForeignKey("messages.id"), nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    keyword: Mapped[str] = mapped_column(String, nullable=False)


class Place(Base):
    __tablename__ = "places"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    name_uk: Mapped[str | None] = mapped_column(String)
    name_ru: Mapped[str | None] = mapped_column(String)
    alt_names: Mapped[str | None] = mapped_column(Text)
    oblast: Mapped[str | None] = mapped_column(String)
    raion: Mapped[str | None] = mapped_column(String)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str | None] = mapped_column(String)


class MessagePlace(Base):
    __tablename__ = "message_places"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(Integer, ForeignKey("messages.id"), nullable=False)
    place_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("places.id"))
    raw_mention: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, default=0)


class CaseBatch(Base):
    __tablename__ = "case_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    source_filename: Mapped[str | None] = mapped_column(String)
    original_path: Mapped[str | None] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String)
    document_date: Mapped[date | None] = mapped_column(Date)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    night_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    rollover_hour: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)
    cases_count: Mapped[int] = mapped_column(Integer, default=0)
    matches_count: Mapped[int] = mapped_column(Integer, default=0)
    approved_count: Mapped[int] = mapped_column(Integer, default=0)
    pending_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("case_batches.id"))
    source_docx: Mapped[str | None] = mapped_column(String)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    event_date: Mapped[date | None] = mapped_column(Date)
    event_time_local: Mapped[str | None] = mapped_column(String)
    time_window_start: Mapped[datetime | None] = mapped_column(DateTime)
    time_window_end: Mapped[datetime | None] = mapped_column(DateTime)
    place_name: Mapped[str | None] = mapped_column(String)
    oblast: Mapped[str | None] = mapped_column(String)
    reference_text: Mapped[str | None] = mapped_column(Text)
    raw_grid_northing: Mapped[str | None] = mapped_column(String)
    raw_grid_easting: Mapped[str | None] = mapped_column(String)
    coordinate_source: Mapped[str | None] = mapped_column(String)
    parser_warnings: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    radius_km: Mapped[float] = mapped_column(Float, default=15)
    attack_type: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class CaseMatch(Base):
    __tablename__ = "case_matches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("cases.id"), nullable=False)
    message_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("messages.id"))
    firms_point_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("firms_points.id"))
    match_type: Mapped[str] = mapped_column(String, nullable=False)
    time_score: Mapped[float] = mapped_column(Float, default=0)
    geo_score: Mapped[float] = mapped_column(Float, default=0)
    keyword_score: Mapped[float] = mapped_column(Float, default=0)
    source_score: Mapped[float] = mapped_column(Float, default=0)
    total_score: Mapped[float] = mapped_column(Float, default=0)
    priority: Mapped[str] = mapped_column(String, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    review_status: Mapped[str] = mapped_column(String, default="pending")
    review_note: Mapped[str | None] = mapped_column(Text)
    score_details_json: Mapped[str | None] = mapped_column(Text)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class FirmsPoint(Base):
    __tablename__ = "firms_points"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("case_batches.id"))
    case_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cases.id"))
    source: Mapped[str] = mapped_column(String, nullable=False)
    satellite: Mapped[str | None] = mapped_column(String)
    instrument: Mapped[str | None] = mapped_column(String)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    acq_date: Mapped[date | None] = mapped_column(Date)
    acq_time: Mapped[str | None] = mapped_column(String)
    acq_datetime_utc: Mapped[datetime | None] = mapped_column(DateTime)
    confidence: Mapped[str | None] = mapped_column(String)
    frp: Mapped[float | None] = mapped_column(Float)
    brightness: Mapped[float | None] = mapped_column(Float)
    daynight: Mapped[str | None] = mapped_column(String)
    raw_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class EvidenceFile(Base):
    __tablename__ = "evidence_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("case_batches.id"))
    case_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cases.id"))
    message_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("messages.id"))
    file_type: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Export(Base):
    __tablename__ = "exports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("case_batches.id"))
    job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("jobs.id"))
    title: Mapped[str | None] = mapped_column(String)
    docx_path: Mapped[str | None] = mapped_column(String)
    html_path: Mapped[str | None] = mapped_column(String)
    zip_path: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("case_batches.id"))
    kind: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="queued", nullable=False)
    input_path: Mapped[str | None] = mapped_column(String)
    output_path: Mapped[str | None] = mapped_column(String)
    params_json: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
