"""Personalised "For you" feed and public view tracking."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from ..errors import ApiError
from ..extensions import db
from ..models import Lecture, VideoGroup, utcnow
from ..serializers import iso, lecture_card
from ..services.recommendations import (
    DEFAULT_LIMIT,
    RecommendationItem,
    public_filter,
    recommendation_service,
)
from . import parse_uuid

bp = Blueprint("recommendations", __name__, url_prefix="/api")


def _item_payload(item: RecommendationItem) -> dict:
    card = lecture_card(item.lecture)
    card.update(
        {
            "owner_name": item.owner_name,
            "group_name": item.group_name,
            "thumbnail_url": (
                f"/api/public/lectures/{item.lecture.id}/thumbnail"
                if item.lecture.thumbnail_path
                else None
            ),
            "recommendation": {
                "score": item.score,
                "reason": item.reason,
                "matched_topics": list(item.matched_topics),
                "personalized": item.personalized,
            },
        }
    )
    return card


@bp.get("/recommendations")
def recommendations():
    if g.user_id is None:
        raise ApiError("Требуется вход", 401, "authentication_required")
    try:
        limit = int(request.args.get("limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, 30))

    session = db.session()
    try:
        feed = recommendation_service.recommend(session, g.user_id, limit=limit)
        return jsonify(
            {
                "mode": feed.mode,
                "fallback": feed.fallback,
                "interests": [
                    {
                        "label": point.label,
                        "kind": point.kind,
                        "weight": round(point.weight, 2),
                    }
                    for point in feed.interests
                ],
                "items": [_item_payload(item) for item in feed.items],
                "generated_at": iso(utcnow()),
            }
        )
    finally:
        session.close()


@bp.post("/public/lectures/<lecture_id>/view")
def record_public_view(lecture_id: str):
    """Count a view and, on the first one, feed the interest profile.

    The route lives under ``/api/public`` so share pages are not blocked by the
    auth middleware; guests still get a view counter, authenticated users also
    get personalisation.
    """
    session = db.session()
    try:
        lecture = (
            session.query(Lecture)
            .outerjoin(VideoGroup, VideoGroup.id == Lecture.group_id)
            .filter(
                Lecture.id == parse_uuid(lecture_id),
                Lecture.status == "ready",
                public_filter(),
            )
            .first()
        )
        if lecture is None:
            raise ApiError("Видео недоступно", 404, "lecture_not_found")

        if g.user_id is None:
            lecture.view_count = int(lecture.view_count or 0) + 1
            session.commit()
            return jsonify(
                {"tracked": False, "view_count": lecture.view_count, "first_view": False}
            )

        first, view_count = recommendation_service.record_view(session, g.user_id, lecture)
        session.commit()
        return jsonify(
            {"tracked": True, "view_count": view_count, "first_view": first}
        )
    finally:
        session.close()
