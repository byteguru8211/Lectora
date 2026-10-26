"""Semantic search across one lecture or the whole course."""

from __future__ import annotations

import logging
import time

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func, select, update

from ..config import Config
from ..errors import ApiError
from ..extensions import db
from ..models import Lecture, SearchLog, Section
from ..services.search import search_service
from . import parse_uuid

bp = Blueprint("search", __name__, url_prefix="/api")
log = logging.getLogger(__name__)


@bp.get("/search")
def search():
    query = (request.args.get("q") or "").strip()
    if len(query) < 2:
        raise ApiError("Введите запрос длиной хотя бы 2 символа", 400, "query_too_short")
    if len(query) > 500:
        raise ApiError("Запрос слишком длинный", 400, "query_too_long")

    lecture_id = parse_uuid(request.args.get("lecture_id"))
    try:
        limit = int(request.args.get("limit", Config.SEARCH_DEFAULT_LIMIT))
    except ValueError:
        limit = Config.SEARCH_DEFAULT_LIMIT
    limit = max(1, min(limit, Config.SEARCH_MAX_LIMIT))
    use_rerank = (request.args.get("rerank", "1") not in {"0", "false", "no"})

    session = db.session()
    started = time.perf_counter()
    try:
        if lecture_id is not None:
            lecture = session.get(Lecture, lecture_id)
            if lecture is None:
                raise ApiError("Лекция не найдена", 404, "lecture_not_found")
            if lecture.status != "ready":
                raise ApiError(
                    "Лекция ещё обрабатывается — поиск станет доступен после индексации.",
                    409,
                    "lecture_not_ready",
                )

        outcome = search_service.search(
            session,
            query,
            lecture_ids=[lecture_id] if lecture_id else None,
            limit=limit,
            use_rerank=use_rerank,
        )

        # analytics + popularity counters
        session.add(
            SearchLog(
                query=query[:500],
                scope="lecture" if lecture_id else "course",
                lecture_id=lecture_id,
                result_count=len(outcome.hits),
                latency_ms=outcome.took_ms,
                reranked=outcome.reranked,
            )
        )
        touched = {hit.lecture_id for hit in outcome.hits}
        if touched:
            session.execute(
                update(Lecture)
                .where(Lecture.id.in_([__import__("uuid").UUID(item) for item in touched]))
                .values(search_hits=Lecture.search_hits + 1)
            )
        session.commit()

        payload = outcome.as_dict()
        payload.update(
            {
                "query": query,
                "scope": "lecture" if lecture_id else "course",
                "limit": limit,
                "took_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return jsonify(payload)
    finally:
        session.close()


@bp.get("/search/suggest")
def suggest():
    query = (request.args.get("q") or "").strip().lower()
    if not query:
        return jsonify({"items": []})
    session = db.session()
    try:
        pattern = f"%{query}%"
        titles = (
            session.query(Lecture.title)
            .filter(Lecture.title.ilike(pattern))
            .limit(5)
            .all()
        )
        sections = (
            session.query(Section.title, Lecture.title, Section.start_sec, Lecture.id)
            .join(Lecture, Lecture.id == Section.lecture_id)
            .filter(Section.title.ilike(pattern))
            .limit(5)
            .all()
        )
        history = (
            session.query(SearchLog.query, func.max(SearchLog.created_at).label("last"))
            .filter(SearchLog.query.ilike(pattern))
            .group_by(SearchLog.query)
            .order_by(func.max(SearchLog.created_at).desc())
            .limit(5)
            .all()
        )
        items: list[dict] = []
        seen: set[str] = set()
        for (title,) in titles:
            if title.lower() not in seen:
                seen.add(title.lower())
                items.append({"text": title, "type": "lecture"})
        for (title, lecture_title, start, lecture_id) in sections:
            if title.lower() in seen:
                continue
            seen.add(title.lower())
            items.append(
                {
                    "text": title,
                    "type": "section",
                    "lecture_id": str(lecture_id),
                    "lecture_title": lecture_title,
                    "start_sec": round(start, 2),
                }
            )
        for (text,) in history:
            if text.lower() in seen:
                continue
            seen.add(text.lower())
            items.append({"text": text, "type": "history"})
        return jsonify({"items": items[:8]})
    finally:
        session.close()
