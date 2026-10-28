"""Schema creation and database-level indexes that SQLAlchemy cannot express."""

from __future__ import annotations

import logging

from sqlalchemy import text

from .models import Base

log = logging.getLogger(__name__)


FTS_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_chunks_fts "
    "ON chunks USING GIN (to_tsvector('russian', text))"
)
TITLE_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_lectures_title_trgm "
    "ON lectures USING GIN (lower(title) gin_trgm_ops)"
)
MIGRATIONS = (
    # 1.0.1: titles generated from the transcript
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS title_auto BOOLEAN NOT NULL DEFAULT FALSE",
    # 1.1.0: optional hierarchy for the personal library
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS subject VARCHAR(100)",
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS topic VARCHAR(120)",
    # 1.2.0: personal accounts and lecture ownership
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE",
    "ALTER TABLE search_logs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE",
    # 1.3.0: per-video hardware acceleration preference
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS use_gpu BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS asr_engine VARCHAR(16) NOT NULL DEFAULT 'vosk'",
    # 1.4.0: roles, user groups and sharing
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(16) NOT NULL DEFAULT 'student'",
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS group_id UUID REFERENCES video_groups(id) ON DELETE SET NULL",
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS visibility VARCHAR(16) NOT NULL DEFAULT 'private'",
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS share_token VARCHAR(64)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_lectures_share_token ON lectures (share_token) WHERE share_token IS NOT NULL",
    # 1.5.0: notes modes (api / local) and richer conspectus
    # (llm_mode_used can be ``offline`` — the extractive fallback marker)
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS llm_mode VARCHAR(16) NOT NULL DEFAULT 'local'",
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS llm_mode_used VARCHAR(16)",
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS questions JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE sections ADD COLUMN IF NOT EXISTS details TEXT",
    # 1.6.0: bilingual transcripts and optional translated narration
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS target_language VARCHAR(8)",
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS voiceover_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS voiceover_path VARCHAR(512)",
    "ALTER TABLE transcript_segments ADD COLUMN IF NOT EXISTS translated_text TEXT",
    # 1.7.0: narration aligned to transcript timecodes
    "ALTER TABLE lectures ADD COLUMN IF NOT EXISTS voiceover_aligned BOOLEAN NOT NULL DEFAULT FALSE",
)


def ensure_schema(engine) -> None:
    """Create tables + full-text index. Safe to run on every boot."""
    Base.metadata.create_all(engine)
    if engine.dialect.name != "postgresql":
        log.warning("non-postgresql database: skipping full-text indexes")
        return
    with engine.begin() as connection:
        for statement in MIGRATIONS:
            connection.execute(text(statement))
        connection.execute(text(FTS_INDEX))
        try:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            connection.execute(text(TITLE_INDEX))
        except Exception:  # pragma: no cover - extension needs superuser
            log.info("pg_trgm not available; title search uses ILIKE only")
    log.info("database schema is up to date")
