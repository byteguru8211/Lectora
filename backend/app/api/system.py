"""Health, capabilities and dashboard statistics."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify
from sqlalchemy import func, text

from ..config import Config
from ..extensions import db
from ..models import Chunk, Job, Lecture, SearchLog, TranscriptSegment
from ..services.asr import AsrService
from ..services.embeddings import embeddings
from ..services.llm import llm
from ..services.media import MediaService
from ..services.reranker import reranker
from ..services.storage import free_disk_gb
from ..utils.timefmt import format_timestamp

bp = Blueprint("system", __name__, url_prefix="/api")
log = logging.getLogger(__name__)


@bp.get("/health")
def health():
    started = time.perf_counter()
    session = db.session()
    database_ok = True
    detail = None
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover
        database_ok = False
        detail = str(exc)[:200]
    finally:
        session.close()

    media = MediaService()
    asr = AsrService()
    profiles = asr.available_profiles()
    llm_health = llm.health()
    checks = {
        "database": {"ok": database_ok, "detail": detail},
        "ffmpeg": {"ok": media.available, "issues": media.tools.issues},
        "asr_models": {"ok": any(profiles.values()), "profiles": profiles},
        "embeddings": {"ok": embeddings.model_path.is_dir()},
        "reranker": {"ok": reranker.available()},
        "llm": llm_health.as_dict(),
        "url_import": {"ok": bool(media.tools.ytdlp)},
    }
    critical = database_ok and media.available and any(profiles.values())
    return (
        jsonify(
            {
                "status": "ok" if critical else "degraded",
                "checks": checks,
                "took_ms": int((time.perf_counter() - started) * 1000),
            }
        ),
        200 if critical else 503,
    )


@bp.get("/system/info")
def info():
    asr = AsrService()
    media = MediaService()
    try:
        import torch
        cuda_available = bool(torch.cuda.is_available())
        cuda_device = torch.cuda.get_device_name(0) if cuda_available else None
    except Exception:
        cuda_available = False
        cuda_device = None
    return jsonify(
        {
            "name": "Lectora",
            "version": current_app.config.get("APP_VERSION", "1.0.0"),
            "asr": {
                "engine": "vosk",
                "profiles": asr.available_profiles(),
                "default": Config.ASR_DEFAULT_PROFILE,
                "sample_rate": Config.ASR_SAMPLE_RATE,
            },
            "embeddings": {
                "model": Config.EMBEDDING_MODEL_PATH.name,
                "device": Config.EMBEDDING_DEVICE,
            },
            "reranker": {
                "enabled": Config.RERANKER_ENABLED,
                "model": Config.RERANKER_MODEL_PATH.name,
            },
            "llm": {
                "enabled": Config.LLM_ENABLED,
                "model": Config.LLM_MODEL,
                "base_url": Config.LLM_BASE_URL,
            },
            "limits": {
                "max_upload_mb": Config.MAX_UPLOAD_MB,
                "search_max_limit": Config.SEARCH_MAX_LIMIT,
            },
            "tools": {
                "ffmpeg": media.tools.ffmpeg,
                "ffprobe": media.tools.ffprobe,
                "yt_dlp": media.tools.ytdlp,
            },
            "acceleration": {
                "cuda": cuda_available,
                "cuda_device": cuda_device,
                "nvenc": media.supports_nvenc(),
            },
        }
    )


@bp.get("/stats")
def stats():
    session = db.session()
    try:
        owned = Lecture.user_id == g.user_id
        total = session.query(func.count(Lecture.id)).filter(owned).scalar() or 0
        ready = (
            session.query(func.count(Lecture.id)).filter(owned, Lecture.status == "ready").scalar() or 0
        )
        processing = (
            session.query(func.count(Lecture.id))
            .filter(owned, Lecture.status.in_(("queued", "processing")))
            .scalar()
            or 0
        )
        failed = (
            session.query(func.count(Lecture.id)).filter(owned, Lecture.status == "failed").scalar() or 0
        )
        duration = session.query(func.coalesce(func.sum(Lecture.duration_sec), 0)).filter(owned).scalar() or 0
        words = session.query(func.coalesce(func.sum(Lecture.word_count), 0)).filter(owned).scalar() or 0
        chunks = session.query(func.count(Chunk.id)).join(Lecture, Lecture.id == Chunk.lecture_id).filter(owned).scalar() or 0
        segments = session.query(func.count(TranscriptSegment.id)).join(Lecture, Lecture.id == TranscriptSegment.lecture_id).filter(owned).scalar() or 0
        searches = session.query(func.count(SearchLog.id)).filter(SearchLog.user_id == g.user_id).scalar() or 0
        searches_today = (
            session.query(func.count(SearchLog.id))
            .filter(SearchLog.user_id == g.user_id, SearchLog.created_at >= func.now() - text("interval '24 hours'"))
            .scalar()
            or 0
        )
        pending_jobs = (
            session.query(func.count(Job.id)).join(Lecture, Lecture.id == Job.lecture_id).filter(owned, Job.status.in_(("queued", "running"))).scalar()
            or 0
        )
        top = (
            session.query(Lecture.id, Lecture.title, Lecture.view_count, Lecture.duration_sec)
            .filter(owned, Lecture.status == "ready")
            .order_by(Lecture.view_count.desc())
            .limit(4)
            .all()
        )
        recent_queries = (
            session.query(SearchLog.query, func.max(SearchLog.created_at))
            .filter(SearchLog.user_id == g.user_id)
            .group_by(SearchLog.query)
            .order_by(func.max(SearchLog.created_at).desc())
            .limit(6)
            .all()
        )

        storage_root = Path(Config.STORAGE_DIR)
        used_bytes = 0
        if storage_root.exists():
            for path in storage_root.rglob("*"):
                if path.is_file():
                    used_bytes += path.stat().st_size

        return jsonify(
            {
                "lectures": {
                    "total": total,
                    "ready": ready,
                    "processing": processing,
                    "failed": failed,
                },
                "content": {
                    "duration_sec": round(float(duration), 2),
                    "duration_label": format_timestamp(duration),
                    "words": int(words),
                    "chunks": int(chunks),
                    "segments": int(segments),
                },
                "search": {
                    "total": int(searches),
                    "today": int(searches_today),
                    "recent_queries": [row[0] for row in recent_queries],
                },
                "queue": {"pending": int(pending_jobs)},
                "storage": {
                    "used_bytes": used_bytes,
                    "used_gb": round(used_bytes / (1024**3), 2),
                    "free_gb": free_disk_gb(storage_root),
                },
                "top_lectures": [
                    {
                        "id": str(row.id),
                        "title": row.title,
                        "views": row.view_count,
                        "duration_label": format_timestamp(row.duration_sec),
                    }
                    for row in top
                ],
            }
        )
    finally:
        session.close()
