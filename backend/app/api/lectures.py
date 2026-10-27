"""Lecture upload, status, transcript, outline, media and progress stream."""

from __future__ import annotations

import json
import logging
import mimetypes
import time
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    g,
    jsonify,
    request,
    send_file,
    stream_with_context,
)
from sqlalchemy import func, update

from ..config import Config
from ..errors import ApiError
from ..extensions import db
from ..models import Job, Lecture, Section, TranscriptSegment, VideoGroup
from ..serializers import job_dict, lecture_card, lecture_detail, segment_dict
from ..services.asr import AsrService
from ..services.llm_modes import default_mode, normalize_mode
from ..services.pipeline import STAGE_LABELS
from ..services.search import search_service
from ..services.storage import free_disk_gb
from . import get_lecture_or_404, job_runner, storage

bp = Blueprint("lectures", __name__, url_prefix="/api/lectures")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------- helpers
def _clean_title(raw: str | None, fallback: str) -> str:
    title = (raw or "").strip()
    if not title:
        title = fallback
    if len(title) > 300:
        title = title[:297] + "…"
    return title or "Без названия"


def _parse_profile(raw: str | None) -> str:
    profile = (raw or Config.ASR_DEFAULT_PROFILE).strip().lower()
    available = AsrService().available_profiles()
    if profile not in available:
        profile = "accurate" if available.get("accurate") else "fast"
    if not available.get(profile):
        raise ApiError(
            "Модели распознавания речи не найдены в models/vosk.",
            503,
            "asr_model_missing",
            {"available": available},
        )
    return profile


def _parse_engine(raw: str | None) -> str:
    engine = (raw or "vosk").strip().lower()
    if engine not in {"vosk", "whisper"}:
        raise ApiError("Неизвестный движок распознавания", 400, "bad_asr_engine")
    return engine


def _parse_visibility(raw: str | None) -> str:
    value = (raw or "private").strip().lower()
    if value not in {"private", "public"}:
        raise ApiError("Некорректная видимость видео", 400, "bad_visibility")
    return value


def _parse_language(raw: str | None, *, optional: bool = False) -> str | None:
    value = (raw or "").strip().lower()
    if optional and value in {"", "none", "off"}:
        return None
    if value not in {"ru", "en"}:
        raise ApiError("Поддерживаются русский и английский языки", 400, "bad_language")
    return value


def _parse_llm_mode(raw: str | None, default: str | None = None) -> str:
    """Validate the notes mode (``api`` | ``local``)."""
    try:
        return normalize_mode(raw, default or default_mode())
    except ValueError:
        raise ApiError(
            "Неизвестный режим генерации конспекта. Допустимы: api, local.",
            400,
            "bad_llm_mode",
        )


def _parse_group(raw: str | None):
    if not raw:
        return None
    try:
        return __import__("uuid").UUID(str(raw))
    except ValueError:
        raise ApiError("Некорректная группа", 400, "bad_group_id")


def _enqueue(lecture: Lecture) -> int:
    runner = job_runner()
    if runner is None:
        raise ApiError("Фоновая обработка не запущена", 503, "worker_disabled")
    return runner.enqueue(lecture.id)


def _refresh_interests(session, user_id) -> None:
    """Refresh the materialised topic profile after classification changes."""
    if user_id is None:
        return
    try:
        from ..services.recommendations import recommendation_service

        recommendation_service.rebuild_profile(session, user_id)
        session.commit()
    except Exception:
        session.rollback()
        log.exception("interest profile refresh failed for user %s", user_id)


# ---------------------------------------------------------------- collection
@bp.get("")
def list_lectures():
    session = db.session()
    try:
        query = session.query(Lecture).filter(Lecture.user_id == g.user_id)
        status_filter = (request.args.get("status") or "").strip().lower()
        if status_filter and status_filter != "all":
            if status_filter == "processing":
                query = query.filter(Lecture.status.in_(("queued", "processing")))
            else:
                query = query.filter(Lecture.status == status_filter)
        search = (request.args.get("q") or "").strip()
        if search:
            pattern = f"%{search}%"
            query = query.filter(
                (Lecture.title.ilike(pattern)) | (Lecture.description.ilike(pattern))
            )
        total = query.count()
        limit = min(max(int(request.args.get("limit", 60)), 1), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
        rows = (
            query.order_by(Lecture.created_at.desc()).offset(offset).limit(limit).all()
        )
        # Older installations have no classification yet. Give ready videos a
        # deterministic, content-derived fallback without making the request
        # depend on the optional LLM server.
        changed = False
        for row in rows:
            if row.status == "ready" and not row.subject:
                row.subject = str((row.keywords or ["Другое"])[0]).strip().capitalize() or "Другое"
                first_section = session.query(Section.title).filter(Section.lecture_id == row.id).order_by(Section.idx).first()
                row.topic = first_section[0] if first_section else (row.title[:120] or None)
                changed = True
        if changed:
            session.commit()
            _refresh_interests(session, g.user_id)
        return jsonify(
            {"items": [lecture_card(row) for row in rows], "total": total}
        )
    finally:
        session.close()


@bp.post("")
def create_lecture():
    if "file" not in request.files:
        raise ApiError("Прикрепите видеофайл", 400, "file_required")
    uploaded = request.files["file"]
    if not uploaded or not uploaded.filename:
        raise ApiError("Пустое имя файла", 400, "file_required")

    store = storage()
    key = store.new_key()
    free_gb = free_disk_gb(store.media_root)
    upload_gb = (request.content_length or 0) / (1024**3)
    required_gb = Config.MIN_FREE_DISK_GB + upload_gb
    if free_gb is not None and free_gb < required_gb:
        raise ApiError(
            f"Недостаточно места для загрузки: свободно {free_gb:.1f} ГБ, "
            f"нужно не менее {required_gb:.1f} ГБ.",
            507,
            "insufficient_storage",
        )
    raw_title = (request.form.get("title") or "").strip()
    lecture = Lecture(
        user_id=g.user_id,
        storage_key=key,
        title=_clean_title(raw_title, Path(uploaded.filename).stem),
        title_auto=not raw_title,
        description=(request.form.get("description") or "").strip() or None,
        asr_profile=_parse_profile(request.form.get("asr_profile")),
        asr_engine=_parse_engine(request.form.get("asr_engine")),
        use_gpu=(request.form.get("use_gpu", "false").strip().lower() in {"1", "true", "yes", "on"}),
        llm_mode=_parse_llm_mode(request.form.get("llm_mode")),
        language=_parse_language(request.form.get("language") or "ru"),
        target_language=_parse_language(request.form.get("target_language"), optional=True),
        voiceover_enabled=(request.form.get("voiceover", "false").strip().lower() in {"1", "true", "yes", "on"}),
        visibility=_parse_visibility(request.form.get("visibility")),
        group_id=_parse_group(request.form.get("group_id")),
        source_type="upload",
        original_filename=uploaded.filename[:255],
        status="queued",
        stage="queued",
        progress=0.0,
    )
    session = db.session()
    try:
        if lecture.language == "en":
            lecture.asr_engine = "whisper"
        if lecture.target_language and lecture.llm_mode != "api":
            raise ApiError("Перевод видео доступен только через DeepSeek API", 400, "translation_requires_api")
        if lecture.voiceover_enabled and not lecture.target_language:
            raise ApiError("Для озвучки сначала выберите язык перевода", 400, "voiceover_requires_translation")
        if lecture.group_id and session.query(VideoGroup).filter(VideoGroup.id == lecture.group_id, VideoGroup.owner_id == g.user_id).first() is None:
            raise ApiError("Группа не найдена", 404, "group_not_found")
        target, size = store.save_upload(
            uploaded, key, max_bytes=Config.MAX_UPLOAD_MB * 1024 * 1024
        )
        lecture.video_path = store.relative(target)
        lecture.mime_type = uploaded.mimetype or mimetypes.guess_type(target.name)[0]
        session.add(lecture)
        session.commit()
        job_id = _enqueue(lecture)
        log.info("uploaded lecture %s (%s, %.1f MB)", lecture.id, target.name, size / 1e6)
        payload = lecture_card(lecture)
        payload["job_id"] = job_id
        return jsonify(payload), 202
    except Exception:
        session.rollback()
        store.delete_lecture(key)
        raise
    finally:
        session.close()


@bp.post("/import")
def import_lecture():
    if not Config.ALLOW_URL_IMPORT:
        raise ApiError("Импорт по ссылке отключён", 403, "import_disabled")
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ApiError("Укажите корректную ссылку на видео", 400, "bad_url")

    store = storage()
    key = store.new_key()
    free_gb = free_disk_gb(store.media_root)
    if free_gb is not None and free_gb < Config.MIN_FREE_DISK_GB:
        raise ApiError(
            f"Недостаточно места для импорта: свободно {free_gb:.1f} ГБ, "
            f"нужно не менее {Config.MIN_FREE_DISK_GB:.1f} ГБ.",
            507,
            "insufficient_storage",
        )
    session = db.session()
    try:
        raw_title = (data.get("title") or "").strip()
        lecture = Lecture(
            user_id=g.user_id,
            storage_key=key,
            title=_clean_title(raw_title, "Импорт по ссылке"),
            title_auto=not raw_title,
            description=(data.get("description") or "").strip() or None,
            asr_profile=_parse_profile(data.get("asr_profile")),
            asr_engine=_parse_engine(data.get("asr_engine")),
            use_gpu=bool(data.get("use_gpu", False)),
            llm_mode=_parse_llm_mode(data.get("llm_mode")),
            language=_parse_language(data.get("language") or "ru"),
            target_language=_parse_language(data.get("target_language"), optional=True),
            voiceover_enabled=bool(data.get("voiceover", False)),
            visibility=_parse_visibility(data.get("visibility")),
            group_id=_parse_group(data.get("group_id")),
            source_type="url",
            source_url=url,
            status="queued",
            stage="queued",
            progress=0.0,
        )
        if lecture.language == "en":
            lecture.asr_engine = "whisper"
        if lecture.target_language and lecture.llm_mode != "api":
            raise ApiError("Перевод видео доступен только через DeepSeek API", 400, "translation_requires_api")
        if lecture.voiceover_enabled and not lecture.target_language:
            raise ApiError("Для озвучки сначала выберите язык перевода", 400, "voiceover_requires_translation")
        if lecture.group_id and session.query(VideoGroup).filter(VideoGroup.id == lecture.group_id, VideoGroup.owner_id == g.user_id).first() is None:
            raise ApiError("Группа не найдена", 404, "group_not_found")
        session.add(lecture)
        session.commit()
        job_id = _enqueue(lecture)
        payload = lecture_card(lecture)
        payload["job_id"] = job_id
        return jsonify(payload), 202
    except Exception:
        session.rollback()
        store.delete_lecture(key)
        raise
    finally:
        session.close()


# ---------------------------------------------------------------- single item
@bp.get("/<lecture_id>")
def get_lecture(lecture_id: str):
    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        sections = (
            session.query(Section)
            .filter(Section.lecture_id == lecture.id)
            .order_by(Section.idx)
            .all()
        )
        if lecture.status == "ready":
            session.execute(
                update(Lecture)
                .where(Lecture.id == lecture.id)
                .values(view_count=Lecture.view_count + 1)
            )
            session.commit()
        return jsonify(lecture_detail(lecture, sections))
    finally:
        session.close()


@bp.patch("/<lecture_id>")
def update_lecture(lecture_id: str):
    data = request.get_json(silent=True) or {}
    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        if "title" in data:
            title = _clean_title(data.get("title"), lecture.title)
            lecture.title = title
            lecture.title_auto = False
        if "description" in data:
            lecture.description = (data.get("description") or "").strip() or None
        if "subject" in data:
            lecture.subject = (data.get("subject") or "").strip()[:100] or None
        if "topic" in data:
            lecture.topic = (data.get("topic") or "").strip()[:120] or None
        if "visibility" in data:
            lecture.visibility = _parse_visibility(data.get("visibility"))
        if "group_id" in data:
            group_id = _parse_group(data.get("group_id"))
            if group_id and session.query(VideoGroup).filter(VideoGroup.id == group_id, VideoGroup.owner_id == g.user_id).first() is None:
                raise ApiError("Группа не найдена", 404, "group_not_found")
            lecture.group_id = group_id
        if lecture.topic and not lecture.subject:
            raise ApiError("Для темы нужно выбрать предмет", 400, "subject_required")
        session.commit()
        _refresh_interests(session, g.user_id)
        return jsonify(lecture_card(lecture))
    finally:
        session.close()


@bp.delete("/<lecture_id>")
def delete_lecture(lecture_id: str):
    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        key = lecture.storage_key
        session.delete(lecture)
        session.commit()
        storage().delete_lecture(key)
        search_service.invalidate(lecture.id)
        _refresh_interests(session, g.user_id)
        return ("", 204)
    finally:
        session.close()


@bp.post("/<lecture_id>/reprocess")
def reprocess(lecture_id: str):
    data = request.get_json(silent=True) or {}
    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        if lecture.status in ("queued", "processing"):
            raise ApiError("Лекция уже обрабатывается", 409, "already_processing")
        if data.get("asr_profile"):
            lecture.asr_profile = _parse_profile(data["asr_profile"])
        if data.get("llm_mode"):
            lecture.llm_mode = _parse_llm_mode(data["llm_mode"])
        if lecture.target_language and lecture.llm_mode != "api":
            raise ApiError("Перевод видео доступен только через DeepSeek API", 400, "translation_requires_api")
        lecture.status = "queued"
        lecture.stage = "queued"
        lecture.progress = 0.0
        lecture.error_message = None
        session.commit()
        job_id = _enqueue(lecture)
        payload = lecture_card(lecture)
        payload["job_id"] = job_id
        return jsonify(payload), 202
    finally:
        session.close()


@bp.post("/<lecture_id>/notes")
def rebuild_notes(lecture_id: str):
    """Regenerate only the conspectus with another LLM mode.

    The transcript, semantic index and Q&A history stay untouched, so switching
    between DeepSeek API and the local model is cheap.
    """
    data = request.get_json(silent=True) or {}
    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        if lecture.status in ("queued", "processing"):
            raise ApiError("Лекция уже обрабатывается", 409, "already_processing")
        if not lecture.segment_count:
            raise ApiError(
                "Сначала нужна расшифровка — запустите полную обработку лекции.",
                409,
                "transcript_missing",
            )
        if data.get("llm_mode"):
            lecture.llm_mode = _parse_llm_mode(data["llm_mode"])
        lecture_uuid = lecture.id
        mode = lecture.llm_mode
        session.commit()
        runner = job_runner()
        if runner is None:
            raise ApiError("Фоновая обработка не запущена", 503, "worker_disabled")
        job_id = runner.enqueue(lecture_uuid, kind="notes")
        # enqueue() reuses the scoped session and closes it, so re-read the row
        # instead of refreshing a now-detached instance.
        fresh = session.get(Lecture, lecture_uuid) or lecture
        payload = lecture_card(fresh)
        payload["job_id"] = job_id
        log.info("notes regeneration queued for %s (mode=%s)", lecture_uuid, mode)
        return jsonify(payload), 202
    finally:
        session.close()


@bp.get("/<lecture_id>/transcript")
def transcript(lecture_id: str):
    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        rows = (
            session.query(TranscriptSegment)
            .filter(TranscriptSegment.lecture_id == lecture.id)
            .order_by(TranscriptSegment.idx)
            .all()
        )
        return jsonify(
            {
                "lecture_id": str(lecture.id),
                "duration_sec": round(lecture.duration_sec or 0.0, 2),
                "language": lecture.language,
                "segments": [segment_dict(row) for row in rows],
            }
        )
    finally:
        session.close()


@bp.get("/<lecture_id>/structure")
def structure(lecture_id: str):
    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        sections = (
            session.query(Section)
            .filter(Section.lecture_id == lecture.id)
            .order_by(Section.idx)
            .all()
        )
        from ..serializers import section_dict

        return jsonify(
            {
                "summary": lecture.summary,
                "keywords": list(lecture.keywords or []),
                "questions": list(lecture.questions or []),
                "sections": [section_dict(row) for row in sections],
                "llm_model": lecture.llm_model,
                "llm_mode": lecture.llm_mode,
                "llm_mode_used": lecture.llm_mode_used,
            }
        )
    finally:
        session.close()


@bp.get("/<lecture_id>/status")
def status(lecture_id: str):
    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        job = (
            session.query(Job)
            .filter(Job.lecture_id == lecture.id)
            .order_by(Job.id.desc())
            .first()
        )
        return jsonify(
            {
                "id": str(lecture.id),
                "status": lecture.status,
                "stage": lecture.stage,
                "stage_label": STAGE_LABELS.get(lecture.stage or "", lecture.stage),
                "progress": round(lecture.progress or 0.0, 1),
                "error_message": lecture.error_message,
                "job": job_dict(job) if job else None,
            }
        )
    finally:
        session.close()


# ---------------------------------------------------------------- stream
@bp.get("/<lecture_id>/events")
def events(lecture_id: str):
    """Server-sent events with processing progress (polling DB, change-only)."""
    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        lecture_uuid = lecture.id
    finally:
        session.close()

    def generator():
        last_payload = None
        deadline = time.time() + 3600
        try:
            while time.time() < deadline:
                session = db.session()
                try:
                    current = session.get(Lecture, lecture_uuid)
                    if current is None:
                        yield "event: gone\ndata: {}\n\n"
                        return
                    payload = {
                        "status": current.status,
                        "stage": current.stage,
                        "stage_label": STAGE_LABELS.get(current.stage or "", current.stage),
                        "progress": round(current.progress or 0.0, 1),
                        "error_message": current.error_message,
                        "duration_sec": round(current.duration_sec or 0.0, 2),
                    }
                finally:
                    session.close()
                serialised = json.dumps(payload, ensure_ascii=False)
                if serialised != last_payload:
                    yield f"event: progress\ndata: {serialised}\n\n"
                    last_payload = serialised
                if payload["status"] in ("ready", "failed", "cancelled"):
                    yield f"event: done\ndata: {serialised}\n\n"
                    return
                time.sleep(0.9)
            yield "event: timeout\ndata: {}\n\n"
        except GeneratorExit:  # pragma: no cover - client disconnect
            return

    response = Response(stream_with_context(generator()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    return response


# ---------------------------------------------------------------- files
@bp.get("/<lecture_id>/media")
def media(lecture_id: str):
    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        path = storage().path_for(lecture.video_path)
        if path is None or not path.is_file():
            raise ApiError("Видеофайл недоступен", 404, "media_missing")
        mimetype = lecture.mime_type or mimetypes.guess_type(path.name)[0] or "video/mp4"
        response = send_file(
            path,
            mimetype=mimetype,
            conditional=True,
            etag=True,
            max_age=3600,
            last_modified=path.stat().st_mtime,
        )
        response.headers["Accept-Ranges"] = "bytes"
        response.headers["Content-Disposition"] = "inline"
        return response
    finally:
        session.close()


@bp.get("/<lecture_id>/thumbnail")
def thumbnail(lecture_id: str):
    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        path = storage().path_for(lecture.thumbnail_path)
        if path is None or not path.is_file():
            raise ApiError("Превью недоступно", 404, "thumbnail_missing")
        response = send_file(path, mimetype="image/jpeg", max_age=86400, conditional=True)
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response
    finally:
        session.close()


@bp.get("/<lecture_id>/subtitles.vtt")
def subtitles(lecture_id: str):
    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        rows = (
            session.query(TranscriptSegment)
            .filter(TranscriptSegment.lecture_id == lecture.id)
            .order_by(TranscriptSegment.idx)
            .all()
        )
        from ..utils.timefmt import vtt_time

        lines = ["WEBVTT", ""]
        requested = (request.args.get("lang") or lecture.language).lower()
        if requested not in {lecture.language, lecture.target_language}:
            raise ApiError("Субтитры на этом языке недоступны", 404, "subtitles_unavailable")
        for row in rows:
            value = row.translated_text if requested == lecture.target_language else row.text
            text = (value or row.text).replace("-->", "->")
            lines.append(f"{vtt_time(row.start_sec)} --> {vtt_time(row.end_sec)}")
            lines.append(text)
            lines.append("")
        response = Response("\n".join(lines), mimetype="text/vtt")
        response.headers["Cache-Control"] = "public, max-age=300"
        return response
    finally:
        session.close()


@bp.get("/<lecture_id>/voiceover")
def voiceover(lecture_id: str):
    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        path = storage().path_for(lecture.voiceover_path)
        if path is None or not path.is_file():
            raise ApiError("Озвучка недоступна", 404, "voiceover_missing")
        return send_file(path, mimetype="audio/mpeg", conditional=True, etag=True, max_age=3600)
    finally:
        session.close()


# ---------------------------------------------------------------- queue info
@bp.get("/queue/status")
def queue_status():
    session = db.session()
    try:
        pending = session.query(func.count(Job.id)).filter(
            Job.status.in_(("queued", "running"))
        ).scalar()
        latest = (
            session.query(Job).order_by(Job.id.desc()).limit(5).all()
        )
        return jsonify(
            {
                "pending": int(pending or 0),
                "recent": [job_dict(job) for job in latest],
            }
        )
    finally:
        session.close()
