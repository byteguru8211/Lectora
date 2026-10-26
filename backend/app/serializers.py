"""JSON serialisers: one place that decides what the API exposes."""

from __future__ import annotations

from typing import Iterable

from .models import Job, Lecture, QaMessage, Section, TranscriptSegment
from .services.pipeline import STAGE_LABELS
from .utils.timefmt import format_timestamp
from .utils.text import truncate


def iso(value) -> str | None:
    return value.isoformat() if value else None


def lecture_card(lecture: Lecture) -> dict:
    return {
        "id": str(lecture.id),
        "title": lecture.title,
        "title_auto": lecture.title_auto,
        "description": lecture.description,
        "subject": lecture.subject,
        "topic": lecture.topic,
        "status": lecture.status,
        "stage": lecture.stage,
        "stage_label": STAGE_LABELS.get(lecture.stage or "", lecture.stage),
        "progress": round(lecture.progress or 0.0, 1),
        "duration_sec": round(lecture.duration_sec or 0.0, 2),
        "duration_label": format_timestamp(lecture.duration_sec),
        "resolution": f"{lecture.width}×{lecture.height}" if lecture.width else None,
        "thumbnail_url": (
            f"/api/lectures/{lecture.id}/thumbnail" if lecture.thumbnail_path else None
        ),
        "source_type": lecture.source_type,
        "source_url": lecture.source_url,
        "asr_profile": lecture.asr_profile,
        "segment_count": lecture.segment_count,
        "chunk_count": lecture.chunk_count,
        "word_count": lecture.word_count,
        "view_count": lecture.view_count,
        "search_hits": lecture.search_hits,
        "error_message": lecture.error_message,
        "llm_model": lecture.llm_model,
        "keywords": list(lecture.keywords or [])[:6],
        "created_at": iso(lecture.created_at),
        "processed_at": iso(lecture.processed_at),
        "processing_ms": lecture.processing_ms,
    }


def lecture_detail(lecture: Lecture, sections: Iterable[Section] | None = None) -> dict:
    data = lecture_card(lecture)
    data.update(
        {
            "summary": lecture.summary,
            "keywords": list(lecture.keywords or []),
            "sections": [section_dict(section) for section in (sections or [])],
            "media_url": f"/api/lectures/{lecture.id}/media",
            "subtitles_url": f"/api/lectures/{lecture.id}/subtitles.vtt",
            "created_at": iso(lecture.created_at),
            "updated_at": iso(lecture.updated_at),
        }
    )
    return data


def section_dict(section: Section) -> dict:
    return {
        "id": section.id,
        "idx": section.idx,
        "title": section.title,
        "summary": section.summary,
        "start_sec": round(section.start_sec, 2),
        "end_sec": round(section.end_sec, 2),
        "timestamp": format_timestamp(section.start_sec),
        "duration_sec": round(max(0.0, section.end_sec - section.start_sec), 2),
        "key_points": list(section.key_points or []),
    }


def segment_dict(segment: TranscriptSegment) -> dict:
    return {
        "idx": segment.idx,
        "start_sec": round(segment.start_sec, 2),
        "end_sec": round(segment.end_sec, 2),
        "timestamp": format_timestamp(segment.start_sec),
        "text": segment.text,
    }


def qa_dict(message: QaMessage) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "citations": list(message.citations or []),
        "grounded": message.grounded,
        "created_at": iso(message.created_at),
    }


def job_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "lecture_id": str(job.lecture_id),
        "status": job.status,
        "stage": job.stage,
        "progress": round(job.progress or 0.0, 1),
        "attempts": job.attempts,
        "error": job.error_message,
        "created_at": iso(job.created_at),
        "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at),
    }


def search_summary(result) -> dict:  # type: ignore[no-untyped-def]
    data = result.as_dict()
    for hit in data["results"]:
        hit["snippet"] = truncate(hit["snippet"], 300)
    return data
