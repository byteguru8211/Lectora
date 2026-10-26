"""HTTP API blueprints."""

from __future__ import annotations

import uuid

from flask import current_app, g

from ..errors import ApiError


def storage():
    return current_app.extensions["storage"]


def job_runner():
    return current_app.extensions.get("job_runner")


def pipeline_service():
    return current_app.extensions["pipeline"]


def get_lecture_or_404(session, raw_id: str):
    from ..models import Lecture

    try:
        lecture_id = uuid.UUID(str(raw_id))
    except (ValueError, AttributeError, TypeError):
        raise ApiError("Некорректный идентификатор лекции", 400, "bad_lecture_id")
    lecture = session.get(Lecture, lecture_id)
    if lecture is None or lecture.user_id != getattr(g, "user_id", None):
        raise ApiError("Лекция не найдена", 404, "lecture_not_found")
    return lecture


def parse_uuid(raw: str | None) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError):
        raise ApiError("Некорректный идентификатор", 400, "bad_uuid")
