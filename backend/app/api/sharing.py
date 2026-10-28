"""User collections, public catalogue and token-based private sharing."""

from __future__ import annotations

import secrets
import time
import uuid

from flask import Blueprint, Response, g, jsonify, request, send_file
from sqlalchemy import and_, func, or_

from ..errors import ApiError
from ..extensions import db
from ..models import ExamSheet, Lecture, Section, TranscriptSegment, User, VideoGroup
from ..serializers import lecture_card, lecture_detail, segment_dict
from ..services.exam import (
    build_exam_sheet,
    current_fingerprint,
    group_mode_hint,
    save_exam_sheet,
    sheet_payload,
)
from ..services.qa import qa_service
from ..services.search import search_service
from . import storage

bp = Blueprint("sharing", __name__, url_prefix="/api")


def _uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError):
        raise ApiError("Некорректный идентификатор", 400, "bad_uuid")


def _group_dict(group: VideoGroup, count: int = 0) -> dict:
    return {"id": str(group.id), "name": group.name, "description": group.description, "visibility": group.visibility, "share_token": group.share_token, "video_count": count, "created_at": group.created_at.isoformat() if group.created_at else None}


def _owned_group(session, raw_id: str) -> VideoGroup:
    group = session.get(VideoGroup, _uuid(raw_id))
    if group is None or group.owner_id != g.user_id:
        raise ApiError("Группа не найдена", 404, "group_not_found")
    return group


@bp.get("/groups")
def list_groups():
    session = db.session()
    try:
        rows = session.query(VideoGroup, func.count(Lecture.id)).outerjoin(Lecture, Lecture.group_id == VideoGroup.id).filter(VideoGroup.owner_id == g.user_id).group_by(VideoGroup.id).order_by(VideoGroup.created_at.desc()).all()
        return jsonify({"items": [_group_dict(group, count) for group, count in rows]})
    finally:
        session.close()


@bp.post("/groups")
def create_group():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    visibility = (data.get("visibility") or "private").strip().lower()
    if not 2 <= len(name) <= 160:
        raise ApiError("Название группы должно содержать от 2 до 160 символов", 400, "bad_group_name")
    if visibility not in {"private", "public"}:
        raise ApiError("Некорректная видимость группы", 400, "bad_visibility")
    session = db.session()
    try:
        group = VideoGroup(owner_id=g.user_id, name=name, description=(data.get("description") or "").strip() or None, visibility=visibility)
        session.add(group)
        session.commit()
        return jsonify(_group_dict(group)), 201
    finally:
        session.close()


@bp.patch("/groups/<group_id>")
def update_group(group_id: str):
    data = request.get_json(silent=True) or {}
    session = db.session()
    try:
        group = _owned_group(session, group_id)
        if "name" in data:
            name = (data.get("name") or "").strip()
            if not 2 <= len(name) <= 160:
                raise ApiError("Некорректное название группы", 400, "bad_group_name")
            group.name = name
        if "visibility" in data:
            visibility = (data.get("visibility") or "").strip().lower()
            if visibility not in {"private", "public"}:
                raise ApiError("Некорректная видимость", 400, "bad_visibility")
            group.visibility = visibility
        session.commit()
        count = session.query(func.count(Lecture.id)).filter(Lecture.group_id == group.id).scalar() or 0
        return jsonify(_group_dict(group, count))
    finally:
        session.close()


def _exam_payload(session, group: VideoGroup, *, can_generate: bool) -> dict:
    fingerprint, count = current_fingerprint(session, group)
    sheet = session.query(ExamSheet).filter(ExamSheet.group_id == group.id).first()
    payload = sheet_payload(sheet, fingerprint=fingerprint, lecture_count=count)
    payload.update(
        group=_group_dict(group, count),
        can_generate=can_generate and count > 0,
        mode_hint=group_mode_hint(session, group),
    )
    return payload


@bp.get("/groups/<group_id>/exam")
def get_group_exam(group_id: str):
    session = db.session()
    try:
        group = _owned_group(session, group_id)
        return jsonify(_exam_payload(session, group, can_generate=True))
    finally:
        session.close()


@bp.post("/groups/<group_id>/exam")
def build_group_exam(group_id: str):
    data = request.get_json(silent=True) or {}
    session = db.session()
    try:
        group = _owned_group(session, group_id)
        try:
            result = build_exam_sheet(session, group, mode=data.get("mode"))
        except ValueError:
            raise ApiError(
                "В группе пока нет готовых лекций — шпаргалку не из чего собрать.",
                409,
                "no_ready_lectures",
            )
        save_exam_sheet(session, group, result)
        return jsonify(_exam_payload(session, group, can_generate=True))
    finally:
        session.close()


@bp.post("/groups/<group_id>/share")
def share_group(group_id: str):
    session = db.session()
    try:
        group = _owned_group(session, group_id)
        group.share_token = group.share_token or secrets.token_urlsafe(24)
        session.commit()
        return jsonify({"token": group.share_token, "path": f"/shared/groups/{group.share_token}"})
    finally:
        session.close()


@bp.post("/lectures/<lecture_id>/share")
def share_lecture(lecture_id: str):
    session = db.session()
    try:
        lecture = session.get(Lecture, _uuid(lecture_id))
        if lecture is None or lecture.user_id != g.user_id:
            raise ApiError("Видео не найдено", 404, "lecture_not_found")
        lecture.share_token = lecture.share_token or secrets.token_urlsafe(24)
        session.commit()
        return jsonify({"token": lecture.share_token, "path": f"/shared/videos/{lecture.share_token}"})
    finally:
        session.close()


def _public_filter():
    return or_(Lecture.visibility == "public", VideoGroup.visibility == "public")


@bp.get("/public/lectures")
def public_lectures():
    session = db.session()
    try:
        rows = session.query(Lecture, User.name, VideoGroup.name).join(User, User.id == Lecture.user_id).outerjoin(VideoGroup, VideoGroup.id == Lecture.group_id).filter(Lecture.status == "ready", _public_filter()).order_by(Lecture.created_at.desc()).limit(200).all()
        items = []
        for lecture, owner_name, group_name in rows:
            item = lecture_card(lecture)
            item.update({"owner_name": owner_name, "group_name": group_name, "thumbnail_url": f"/api/public/lectures/{lecture.id}/thumbnail" if lecture.thumbnail_path else None})
            items.append(item)
        return jsonify({"items": items})
    finally:
        session.close()


def _public_lecture(session, lecture_id: str) -> Lecture:
    lecture = session.query(Lecture).outerjoin(VideoGroup, VideoGroup.id == Lecture.group_id).filter(Lecture.id == _uuid(lecture_id), _public_filter()).first()
    if lecture is None:
        raise ApiError("Видео недоступно", 404, "lecture_not_found")
    return lecture


# ------------------------------------------------------------ public groups
def _public_group(session, group_id: str) -> VideoGroup:
    group = session.query(VideoGroup).filter(VideoGroup.id == _uuid(group_id), VideoGroup.visibility == "public").first()
    if group is None:
        raise ApiError("Группа недоступна", 404, "group_not_found")
    return group


def _public_group_card(group: VideoGroup, owner_name: str, count: int, duration: float, exam_ready: bool) -> dict:
    return {
        "id": str(group.id),
        "name": group.name,
        "description": group.description,
        "owner_name": owner_name,
        "video_count": count,
        "duration_sec": round(duration or 0.0, 1),
        "exam_ready": exam_ready,
        "created_at": group.created_at.isoformat() if group.created_at else None,
    }


def _public_group_payload(session, group: VideoGroup) -> dict:
    owner_name = session.query(User.name).filter(User.id == group.owner_id).scalar() or "Автор"
    rows = session.query(Lecture).filter(Lecture.group_id == group.id, Lecture.status == "ready").order_by(Lecture.created_at.desc()).all()
    items = []
    duration = 0.0
    for lecture in rows:
        item = lecture_card(lecture)
        item["thumbnail_url"] = f"/api/public/lectures/{lecture.id}/thumbnail" if lecture.thumbnail_path else None
        items.append(item)
        duration += lecture.duration_sec or 0.0
    sheet = session.query(ExamSheet).filter(ExamSheet.group_id == group.id).first()
    return {
        "group": _public_group_card(group, owner_name, len(items), duration, sheet is not None),
        "items": items,
        "exam_ready": sheet is not None,
    }


@bp.get("/public/groups")
def public_groups():
    """Catalogue of public groups — the entry point to a group cheat sheet.

    Only groups with at least one ready lecture are listed: an empty group has
    nothing to open and nothing to build a sheet from.
    """
    session = db.session()
    try:
        rows = (
            session.query(
                VideoGroup,
                User.name,
                func.count(Lecture.id),
                func.coalesce(func.sum(Lecture.duration_sec), 0.0),
            )
            .join(User, User.id == VideoGroup.owner_id)
            .outerjoin(Lecture, and_(Lecture.group_id == VideoGroup.id, Lecture.status == "ready"))
            .filter(VideoGroup.visibility == "public")
            .group_by(VideoGroup.id, User.name)
            .order_by(VideoGroup.created_at.desc())
            .all()
        )
        rows = [row for row in rows if row[2]]
        group_ids = [row[0].id for row in rows]
        ready: set = set()
        if group_ids:
            ready = {group_id for (group_id,) in session.query(ExamSheet.group_id).filter(ExamSheet.group_id.in_(group_ids)).all()}
        items = [
            _public_group_card(group, owner_name, count, duration, group.id in ready)
            for group, owner_name, count, duration in rows
        ]
        return jsonify({"items": items})
    finally:
        session.close()


@bp.get("/public/groups/<group_id>")
def public_group(group_id: str):
    session = db.session()
    try:
        return jsonify(_public_group_payload(session, _public_group(session, group_id)))
    finally:
        session.close()


@bp.get("/public/groups/<group_id>/exam")
def public_group_exam(group_id: str):
    session = db.session()
    try:
        return jsonify(_exam_payload(session, _public_group(session, group_id), can_generate=True))
    finally:
        session.close()


@bp.post("/public/groups/<group_id>/exam")
def build_public_group_exam(group_id: str):
    # Public reads are anonymous by design, but building runs an LLM call:
    # keep that behind authentication even though the group is open.
    if g.user_id is None:
        raise ApiError("Требуется вход", 401, "authentication_required")
    data = request.get_json(silent=True) or {}
    session = db.session()
    try:
        group = _public_group(session, group_id)
        try:
            result = build_exam_sheet(session, group, mode=data.get("mode"))
        except ValueError:
            raise ApiError(
                "В группе пока нет готовых лекций — шпаргалку не из чего собрать.",
                409,
                "no_ready_lectures",
            )
        save_exam_sheet(session, group, result)
        return jsonify(_exam_payload(session, group, can_generate=True))
    finally:
        session.close()


def _shared_lecture(session, token: str) -> Lecture:
    lecture = session.query(Lecture).filter(Lecture.share_token == token).first()
    if lecture is None:
        raise ApiError("Ссылка недействительна", 404, "share_not_found")
    return lecture


def _detail(session, lecture: Lecture, media_url: str) -> dict:
    sections = session.query(Section).filter(Section.lecture_id == lecture.id).order_by(Section.idx).all()
    data = lecture_detail(lecture, sections)
    data["media_url"] = media_url
    data["thumbnail_url"] = f"{media_url.rsplit('/media', 1)[0]}/thumbnail" if lecture.thumbnail_path else None
    data["subtitles_url"] = f"{media_url.rsplit('/media', 1)[0]}/subtitles.vtt"
    data["subtitles_srt_url"] = f"{media_url.rsplit('/media', 1)[0]}/subtitles.srt"
    data["voiceover_url"] = f"{media_url.rsplit('/media', 1)[0]}/voiceover" if lecture.voiceover_path else None
    return data


def _group_lecture(session, token: str, lecture_id: str) -> Lecture:
    lecture = session.query(Lecture).join(VideoGroup, VideoGroup.id == Lecture.group_id).filter(VideoGroup.share_token == token, Lecture.id == _uuid(lecture_id)).first()
    if lecture is None:
        raise ApiError("Видео недоступно", 404, "lecture_not_found")
    return lecture


def _transcript(session, lecture: Lecture):
    rows = session.query(TranscriptSegment).filter(TranscriptSegment.lecture_id == lecture.id).order_by(TranscriptSegment.idx).all()
    return jsonify({"lecture_id": str(lecture.id), "duration_sec": round(lecture.duration_sec or 0.0, 2), "language": lecture.language, "segments": [segment_dict(row) for row in rows]})


def _search(session, lecture: Lecture):
    query = (request.args.get("q") or "").strip()
    if len(query) < 2:
        raise ApiError("Введите запрос длиной хотя бы 2 символа", 400, "query_too_short")
    try:
        limit = max(1, min(int(request.args.get("limit", 12)), 30))
    except (TypeError, ValueError):
        limit = 12
    outcome = search_service.search(session, query, lecture_ids=[lecture.id], limit=limit, use_rerank=True)
    payload = outcome.as_dict()
    payload.update({"query": query, "scope": "lecture", "limit": limit})
    return jsonify(payload)


def _ask(session, lecture: Lecture):
    question = ((request.get_json(silent=True) or {}).get("question") or "").strip()
    if not 3 <= len(question) <= 800:
        raise ApiError("Вопрос должен содержать от 3 до 800 символов", 400, "bad_question")
    result = qa_service.ask(session, lecture, question)
    now = int(time.time() * 1000)
    return jsonify({
        "question": {"id": now, "role": "user", "content": question, "citations": [], "grounded": True, "created_at": None},
        "answer": {"id": now + 1, "role": "assistant", "content": result.answer, "citations": result.citations, "grounded": result.grounded, "created_at": None},
        "llm_used": result.llm_used,
        "llm_mode": result.mode,
    })


def _subtitles(session, lecture: Lecture, fmt: str = "vtt"):
    from ..utils.subtitles import build_subtitles

    rows = session.query(TranscriptSegment).filter(TranscriptSegment.lecture_id == lecture.id).order_by(TranscriptSegment.idx).all()
    requested = (request.args.get("lang") or lecture.language).lower()
    if requested not in {lecture.language, lecture.target_language}:
        raise ApiError("Субтитры на этом языке недоступны", 404, "subtitles_unavailable")
    body = build_subtitles(
        rows,
        language=lecture.language,
        target_language=lecture.target_language,
        requested=requested,
        fmt=fmt,
    )
    return Response(
        body,
        mimetype="text/vtt" if fmt == "vtt" else "application/x-subrip",
        headers={"Cache-Control": "public, max-age=300"},
    )


def _voiceover(lecture: Lecture):
    path = storage().path_for(lecture.voiceover_path)
    if path is None or not path.is_file():
        raise ApiError("Озвучка недоступна", 404, "voiceover_missing")
    return send_file(path, mimetype="audio/mpeg", conditional=True, etag=True, max_age=3600)


def _send_media(lecture: Lecture, thumbnail: bool = False):
    path = storage().path_for(lecture.thumbnail_path if thumbnail else lecture.video_path)
    if path is None or not path.is_file():
        raise ApiError("Файл недоступен", 404, "media_missing")
    return send_file(path, conditional=True, etag=True, max_age=3600)


@bp.get("/public/lectures/<lecture_id>")
def public_lecture(lecture_id: str):
    session = db.session()
    try:
        lecture = _public_lecture(session, lecture_id)
        return jsonify(_detail(session, lecture, f"/api/public/lectures/{lecture.id}/media"))
    finally:
        session.close()


@bp.get("/public/lectures/<lecture_id>/media")
def public_media(lecture_id: str):
    session = db.session()
    try: return _send_media(_public_lecture(session, lecture_id))
    finally: session.close()


@bp.get("/public/lectures/<lecture_id>/thumbnail")
def public_thumbnail(lecture_id: str):
    session = db.session()
    try: return _send_media(_public_lecture(session, lecture_id), True)
    finally: session.close()


@bp.get("/public/lectures/<lecture_id>/transcript")
def public_transcript(lecture_id: str):
    session = db.session()
    try: return _transcript(session, _public_lecture(session, lecture_id))
    finally: session.close()


@bp.get("/public/lectures/<lecture_id>/search")
def public_search(lecture_id: str):
    session = db.session()
    try: return _search(session, _public_lecture(session, lecture_id))
    finally: session.close()


@bp.post("/public/lectures/<lecture_id>/qa")
def public_qa(lecture_id: str):
    session = db.session()
    try: return _ask(session, _public_lecture(session, lecture_id))
    finally: session.close()


@bp.get("/public/lectures/<lecture_id>/subtitles.vtt")
def public_subtitles(lecture_id: str):
    session = db.session()
    try: return _subtitles(session, _public_lecture(session, lecture_id))
    finally: session.close()


@bp.get("/public/lectures/<lecture_id>/subtitles.srt")
def public_subtitles_srt(lecture_id: str):
    session = db.session()
    try: return _subtitles(session, _public_lecture(session, lecture_id), "srt")
    finally: session.close()


@bp.get("/public/lectures/<lecture_id>/voiceover")
def public_voiceover(lecture_id: str):
    session = db.session()
    try: return _voiceover(_public_lecture(session, lecture_id))
    finally: session.close()


@bp.get("/shared/videos/<token>")
def shared_video(token: str):
    session = db.session()
    try: return jsonify(_detail(session, _shared_lecture(session, token), f"/api/shared/videos/{token}/media"))
    finally: session.close()


@bp.get("/shared/videos/<token>/media")
def shared_video_media(token: str):
    session = db.session()
    try: return _send_media(_shared_lecture(session, token))
    finally: session.close()


@bp.get("/shared/videos/<token>/thumbnail")
def shared_video_thumbnail(token: str):
    session = db.session()
    try: return _send_media(_shared_lecture(session, token), True)
    finally: session.close()


@bp.get("/shared/videos/<token>/transcript")
def shared_video_transcript(token: str):
    session = db.session()
    try: return _transcript(session, _shared_lecture(session, token))
    finally: session.close()


@bp.get("/shared/videos/<token>/search")
def shared_video_search(token: str):
    session = db.session()
    try: return _search(session, _shared_lecture(session, token))
    finally: session.close()


@bp.post("/shared/videos/<token>/qa")
def shared_video_qa(token: str):
    session = db.session()
    try: return _ask(session, _shared_lecture(session, token))
    finally: session.close()


@bp.get("/shared/videos/<token>/subtitles.vtt")
def shared_video_subtitles(token: str):
    session = db.session()
    try: return _subtitles(session, _shared_lecture(session, token))
    finally: session.close()


@bp.get("/shared/videos/<token>/subtitles.srt")
def shared_video_subtitles_srt(token: str):
    session = db.session()
    try: return _subtitles(session, _shared_lecture(session, token), "srt")
    finally: session.close()


@bp.get("/shared/videos/<token>/voiceover")
def shared_video_voiceover(token: str):
    session = db.session()
    try: return _voiceover(_shared_lecture(session, token))
    finally: session.close()


@bp.get("/shared/groups/<token>")
def shared_group(token: str):
    session = db.session()
    try:
        group = session.query(VideoGroup).filter(VideoGroup.share_token == token).first()
        if group is None: raise ApiError("Ссылка недействительна", 404, "share_not_found")
        lectures = session.query(Lecture).filter(Lecture.group_id == group.id, Lecture.status == "ready").order_by(Lecture.created_at.desc()).all()
        items = [lecture_card(item) | {"thumbnail_url": None} for item in lectures]
        return jsonify({"group": _group_dict(group, len(items)), "items": items})
    finally: session.close()


@bp.get("/shared/groups/<token>/exam")
def shared_group_exam(token: str):
    session = db.session()
    try:
        group = session.query(VideoGroup).filter(VideoGroup.share_token == token).first()
        if group is None:
            raise ApiError("Ссылка недействительна", 404, "share_not_found")
        return jsonify(_exam_payload(session, group, can_generate=False))
    finally:
        session.close()


@bp.get("/shared/groups/<token>/lectures/<lecture_id>")
def shared_group_lecture(token: str, lecture_id: str):
    session = db.session()
    try:
        lecture = _group_lecture(session, token, lecture_id)
        return jsonify(_detail(session, lecture, f"/api/shared/groups/{token}/lectures/{lecture.id}/media"))
    finally: session.close()


@bp.get("/shared/groups/<token>/lectures/<lecture_id>/media")
def shared_group_media(token: str, lecture_id: str):
    session = db.session()
    try:
        return _send_media(_group_lecture(session, token, lecture_id))
    finally: session.close()


@bp.get("/shared/groups/<token>/lectures/<lecture_id>/thumbnail")
def shared_group_thumbnail(token: str, lecture_id: str):
    session = db.session()
    try: return _send_media(_group_lecture(session, token, lecture_id), True)
    finally: session.close()


@bp.get("/shared/groups/<token>/lectures/<lecture_id>/transcript")
def shared_group_transcript(token: str, lecture_id: str):
    session = db.session()
    try: return _transcript(session, _group_lecture(session, token, lecture_id))
    finally: session.close()


@bp.get("/shared/groups/<token>/lectures/<lecture_id>/search")
def shared_group_search(token: str, lecture_id: str):
    session = db.session()
    try: return _search(session, _group_lecture(session, token, lecture_id))
    finally: session.close()


@bp.post("/shared/groups/<token>/lectures/<lecture_id>/qa")
def shared_group_qa(token: str, lecture_id: str):
    session = db.session()
    try: return _ask(session, _group_lecture(session, token, lecture_id))
    finally: session.close()


@bp.get("/shared/groups/<token>/lectures/<lecture_id>/subtitles.vtt")
def shared_group_subtitles(token: str, lecture_id: str):
    session = db.session()
    try: return _subtitles(session, _group_lecture(session, token, lecture_id))
    finally: session.close()


@bp.get("/shared/groups/<token>/lectures/<lecture_id>/subtitles.srt")
def shared_group_subtitles_srt(token: str, lecture_id: str):
    session = db.session()
    try: return _subtitles(session, _group_lecture(session, token, lecture_id), "srt")
    finally: session.close()


@bp.get("/shared/groups/<token>/lectures/<lecture_id>/voiceover")
def shared_group_voiceover(token: str, lecture_id: str):
    session = db.session()
    try: return _voiceover(_group_lecture(session, token, lecture_id))
    finally: session.close()
