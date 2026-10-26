"""Database schema.

The model is intentionally small and explicit: a lecture owns its transcript
segments, semantic chunks, generated structure and conversation history.
Processing state is persisted in ``lectures`` (for the UI) and in ``jobs``
(for crash-safe queue recovery).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Lecture(Base):
    __tablename__ = "lectures"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    source_type: Mapped[str] = mapped_column(String(16), default="upload")
    source_url: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(100))

    storage_key: Mapped[str] = mapped_column(String(64), nullable=False)
    video_path: Mapped[str | None] = mapped_column(String(512))
    audio_path: Mapped[str | None] = mapped_column(String(512))
    thumbnail_path: Mapped[str | None] = mapped_column(String(512))

    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(8), default="ru")
    asr_profile: Mapped[str] = mapped_column(String(16), default="accurate")

    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    stage: Mapped[str | None] = mapped_column(String(32))
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text)

    segment_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    transcript_chars: Mapped[int] = mapped_column(Integer, default=0)

    summary: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(JSONB, default=list)
    llm_model: Mapped[str | None] = mapped_column(String(120))
    processing_ms: Mapped[int | None] = mapped_column(Integer)

    view_count: Mapped[int] = mapped_column(Integer, default=0)
    search_hits: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="lecture", cascade="all, delete-orphan", passive_deletes=True
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="lecture", cascade="all, delete-orphan", passive_deletes=True
    )
    sections: Mapped[list["Section"]] = relationship(
        back_populates="lecture",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Section.idx",
    )
    messages: Mapped[list["QaMessage"]] = relationship(
        back_populates="lecture", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"


class TranscriptSegment(Base):
    """A short, subtitle-sized piece of speech with exact timing."""

    __tablename__ = "transcript_segments"
    __table_args__ = (
        Index("ix_segments_lecture_idx", "lecture_id", "idx"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lecture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lectures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    end_sec: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    words: Mapped[list | None] = mapped_column(JSONB)

    lecture: Mapped[Lecture] = relationship(back_populates="segments")


class Chunk(Base):
    """A semantic retrieval unit: ~200 words with an embedding."""

    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_lecture_idx", "lecture_id", "idx"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lecture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lectures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    end_sec: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    dim: Mapped[int] = mapped_column(Integer, default=0)

    lecture: Mapped[Lecture] = relationship(back_populates="chunks")


class Section(Base):
    """A chapter of the generated lecture outline."""

    __tablename__ = "sections"
    __table_args__ = (Index("ix_sections_lecture_idx", "lecture_id", "idx"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lecture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lectures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    end_sec: Mapped[float] = mapped_column(Float, nullable=False)
    key_points: Mapped[list] = mapped_column(JSONB, default=list)

    lecture: Mapped[Lecture] = relationship(back_populates="sections")


class Job(Base):
    """Crash-safe unit of background work (one per lecture processing)."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lecture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lectures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(24), default="process")
    status: Mapped[str] = mapped_column(String(16), default="queued")
    stage: Mapped[str | None] = mapped_column(String(32))
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QaMessage(Base):
    """One turn of the 'ask the lecture' conversation."""

    __tablename__ = "qa_messages"
    __table_args__ = (Index("ix_qa_lecture_created", "lecture_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lecture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lectures.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(12), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    grounded: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    lecture: Mapped[Lecture] = relationship(back_populates="messages")


class SearchLog(Base):
    """Lightweight search analytics (no personal data)."""

    __tablename__ = "search_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), default="course")
    lecture_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lectures.id", ondelete="SET NULL")
    )
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    reranked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
