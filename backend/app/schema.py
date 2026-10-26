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
