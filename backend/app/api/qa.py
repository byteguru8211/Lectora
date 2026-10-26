"""Ask-the-lecture endpoint (retrieval-augmented answers with citations)."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from ..config import Config
from ..errors import ApiError
from ..extensions import db
from ..models import QaMessage
from ..serializers import qa_dict
from ..services.qa import qa_service
from . import get_lecture_or_404

bp = Blueprint("qa", __name__, url_prefix="/api/lectures")
log = logging.getLogger(__name__)


@bp.get("/<lecture_id>/qa")
def history(lecture_id: str):
    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        rows = (
            session.query(QaMessage)
            .filter(QaMessage.lecture_id == lecture.id)
            .order_by(QaMessage.id.asc())
            .limit(Config.QA_HISTORY_LIMIT)
            .all()
        )
        return jsonify({"items": [qa_dict(row) for row in rows]})
    finally:
        session.close()


@bp.post("/<lecture_id>/qa")
def ask(lecture_id: str):
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if len(question) < 3:
        raise ApiError("Задайте вопрос подробнее", 400, "question_too_short")
    if len(question) > 800:
        raise ApiError("Вопрос слишком длинный", 400, "question_too_long")

    session = db.session()
    try:
        lecture = get_lecture_or_404(session, lecture_id)
        if lecture.status != "ready":
            raise ApiError(
                "Лекция ещё обрабатывается — вопрос можно задать после индексации.",
                409,
                "lecture_not_ready",
            )
        result = qa_service.ask(session, lecture, question)

        user_message = QaMessage(
            lecture_id=lecture.id, role="user", content=question, citations=[]
        )
        answer_message = QaMessage(
            lecture_id=lecture.id,
            role="assistant",
            content=result.answer,
            citations=result.citations,
            grounded=result.grounded,
        )
        session.add_all([user_message, answer_message])
        session.commit()
        return jsonify(
            {
                "answer": qa_dict(answer_message),
                "question": qa_dict(user_message),
                "llm_used": result.llm_used,
            }
        )
    finally:
        session.close()
