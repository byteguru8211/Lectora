"""Hybrid semantic search: dense embeddings + PostgreSQL full-text + reranker.

Pipeline
--------
1. Dense recall   — cosine similarity over cached bge-m3 chunk vectors.
2. Lexical recall — ``websearch_to_tsquery('russian', ...)`` + ``ts_rank_cd``.
3. Fusion         — weighted sum of normalised scores (RRF-like behaviour).
4. Rerank         — bge-reranker-v2-m3 re-scores the top candidates.
5. De-duplicate   — near-by hits from the same lecture are collapsed.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from sqlalchemy import func, select

from ..config import Config
from ..errors import ApiError
from ..models import Chunk, Lecture
from ..utils.text import highlight_spans, query_terms, snippet
from ..utils.timefmt import format_timestamp
from .embeddings import embeddings
from .reranker import reranker

log = logging.getLogger(__name__)

_CACHE: dict[uuid.UUID, tuple[tuple, list[dict], np.ndarray]] = {}
_CACHE_LIMIT = 64


@dataclass
class SearchHit:
    chunk_id: int
    lecture_id: str
    lecture_title: str
    start_sec: float
    end_sec: float
    text: str
    snippet: str
    spans: list[dict]
    scores: dict = field(default_factory=dict)

    @property
    def timestamp(self) -> str:
        return format_timestamp(self.start_sec)

    def as_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "lecture": {"id": self.lecture_id, "title": self.lecture_title},
            "start_sec": round(self.start_sec, 2),
            "end_sec": round(self.end_sec, 2),
            "timestamp": self.timestamp,
            "text": self.text,
            "snippet": self.snippet,
            "spans": self.spans,
            "scores": {k: round(float(v), 4) for k, v in self.scores.items()},
        }


@dataclass
class SearchOutcome:
    hits: list[SearchHit]
    reranked: bool
    took_ms: int
    candidate_count: int

    def as_dict(self) -> dict:
        return {
            "results": [hit.as_dict() for hit in self.hits],
            "reranked": self.reranked,
            "took_ms": self.took_ms,
            "candidates": self.candidate_count,
        }


def _normalise(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values
    minimum, maximum = float(values.min()), float(values.max())
    if maximum - minimum < 1e-9:
        return np.zeros_like(values)
    return (values - minimum) / (maximum - minimum)


class SearchService:
    def __init__(self) -> None:
        self._cache = _CACHE
        self._rerank_cache: OrderedDict[tuple, dict[int, float]] = OrderedDict()
        self._rerank_cache_limit = 96

    # -- corpus cache ---------------------------------------------------
    def _lecture_version(self, lecture: Lecture) -> tuple:
        processed = lecture.processed_at
        stamp = processed.timestamp() if isinstance(processed, datetime) else 0.0
        return (str(lecture.id), int(lecture.chunk_count or 0), round(stamp, 3))

    def _corpus(self, session, lecture_ids: list[uuid.UUID]):
        rows: list[dict] = []
        matrices: list[np.ndarray] = []
        for lecture_id in lecture_ids:
            lecture = session.get(Lecture, lecture_id)
            if lecture is None or lecture.status != "ready":
                continue
            version = self._lecture_version(lecture)
            cached = self._cache.get(lecture_id)
            if cached and cached[0] == version:
                _, meta, matrix = cached
            else:
                records = session.execute(
                    select(
                        Chunk.id,
                        Chunk.idx,
                        Chunk.start_sec,
                        Chunk.end_sec,
                        Chunk.text,
                        Chunk.embedding,
                        Chunk.dim,
                    )
                    .where(Chunk.lecture_id == lecture_id)
                    .order_by(Chunk.idx)
                ).all()
                if not records:
                    self._cache.pop(lecture_id, None)
                    continue
                vectors = [
                    embeddings.from_bytes(record.embedding, record.dim) for record in records
                ]
                matrix = np.vstack(vectors).astype(np.float32)
                meta = [
                    {
                        "chunk_id": record.id,
                        "lecture_id": str(lecture_id),
                        "lecture_title": lecture.title,
                        "idx": record.idx,
                        "start_sec": record.start_sec,
                        "end_sec": record.end_sec,
                        "text": record.text,
                    }
                    for record in records
                ]
                self._cache[lecture_id] = (version, meta, matrix)
                if len(self._cache) > _CACHE_LIMIT:
                    self._cache.pop(next(iter(self._cache)))
            rows.extend(meta)
            matrices.append(matrix)
        if not matrices:
            return [], np.zeros((0, 0), dtype=np.float32)
        return rows, np.vstack(matrices)

    # -- search ---------------------------------------------------------
    def search(
        self,
        session,
        query: str,
        *,
        lecture_ids: list[uuid.UUID] | None = None,
        limit: int = 15,
        use_rerank: bool = True,
    ) -> SearchOutcome:
        query = (query or "").strip()
        if len(query) < 2:
            raise ApiError("Слишком короткий запрос", 400, "query_too_short")
        if lecture_ids is None:
            lecture_ids = [
                row[0]
                for row in session.execute(
                    select(Lecture.id).where(Lecture.status == "ready")
                ).all()
            ]
        if not lecture_ids:
            return SearchOutcome([], False, 0, 0)

        started = time.perf_counter()
        limit = max(1, min(limit, Config.SEARCH_MAX_LIMIT))
        meta, matrix = self._corpus(session, lecture_ids)
        if matrix.size == 0 or not meta:
            return SearchOutcome([], False, 0, 0)

        query_vector = embeddings.encode_query(query)
        if query_vector.shape[0] != matrix.shape[1]:
            raise ApiError(
                "Размерность эмбеддингов запроса и индекса не совпадает",
                500,
                "embedding_dim_mismatch",
                {"query": query_vector.shape[0], "index": matrix.shape[1]},
            )

        dense = matrix @ query_vector.astype(np.float32)
        dense_norm = _normalise(dense)

        lexical = self._lexical_scores(
            session, query, [m["chunk_id"] for m in meta]
        )
        lexical_norm = _normalise(
            np.array([lexical.get(m["chunk_id"], 0.0) for m in meta], dtype=np.float32)
        )
        fused = dense_norm + Config.SEARCH_LEXICAL_WEIGHT * lexical_norm

        candidate_count = min(len(meta), Config.SEARCH_CANDIDATES)
        order = np.argsort(fused)[::-1][:candidate_count]

        hits: list[SearchHit] = []
        for position in order:
            item = meta[int(position)]
            hits.append(
                SearchHit(
                    chunk_id=item["chunk_id"],
                    lecture_id=item["lecture_id"],
                    lecture_title=item["lecture_title"],
                    start_sec=item["start_sec"],
                    end_sec=item["end_sec"],
                    text=item["text"],
                    snippet=item["text"],
                    spans=[],
                    scores={
                        "dense": float(dense[int(position)]),
                        "lexical": float(lexical.get(item["chunk_id"], 0.0)),
                        "fused": float(fused[int(position)]),
                    },
                )
            )

        reranked = False
        if use_rerank and Config.RERANKER_ENABLED and len(hits) > 1:
            window = min(len(hits), max(8, Config.RERANKER_TOP_K))
            head = hits[:window]
            scores = self._rerank_scores(query, head)
            if scores is not None:
                reranked = True
                for hit in head:
                    hit.scores["rerank"] = scores[hit.chunk_id]
                head.sort(key=lambda h: h.scores["rerank"], reverse=True)
                hits = head + hits[window:]

        terms = query_terms(query)
        popular: list[SearchHit] = []
        for hit in hits:
            if not self._is_distinct(hit, popular):
                continue
            spans = highlight_spans(hit.text, terms)
            hit.spans = spans
            hit.snippet, hit.spans = snippet(hit.text, spans, limit=340)
            hit.scores["final"] = hit.scores.get("rerank", hit.scores["fused"])
            popular.append(hit)
            if len(popular) >= limit:
                break

        took_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "search %r -> %d hits (%d candidates) in %d ms%s",
            query, len(popular), len(meta), took_ms, " +rerank" if reranked else "",
        )
        return SearchOutcome(popular, reranked, took_ms, len(meta))

    def _rerank_scores(self, query: str, hits: list[SearchHit]) -> dict[int, float] | None:
        """Rerank with an LRU cache: demo-friendly and stable under repeat queries."""
        key = (query.strip().lower(), tuple(hit.chunk_id for hit in hits))
        cached = self._rerank_cache.get(key)
        if cached is not None:
            self._rerank_cache.move_to_end(key)
            return cached
        scores = reranker.rerank(query, [hit.text for hit in hits])
        if scores is None or len(scores) != len(hits):
            return None
        mapping = {hit.chunk_id: float(score) for hit, score in zip(hits, scores)}
        self._rerank_cache[key] = mapping
        if len(self._rerank_cache) > self._rerank_cache_limit:
            self._rerank_cache.popitem(last=False)
        return mapping

    def _lexical_scores(self, session, query: str, chunk_ids: list[int]) -> dict[int, float]:
        if not chunk_ids:
            return {}
        tsquery = func.websearch_to_tsquery("russian", query)
        rank = func.ts_rank_cd(func.to_tsvector("russian", Chunk.text), tsquery)
        rows = session.execute(
            select(Chunk.id, rank.label("rank"))
            .where(Chunk.id.in_(chunk_ids))
            .where(rank > 0)
            .order_by(rank.desc())
            .limit(120)
        ).all()
        return {row.id: float(row.rank) for row in rows}

    @staticmethod
    def _is_distinct(hit: SearchHit, accepted: list[SearchHit], min_gap: float = 12.0) -> bool:
        for other in accepted:
            if other.lecture_id != hit.lecture_id:
                continue
            if abs(other.start_sec - hit.start_sec) < min_gap:
                return False
        return True

    def invalidate(self, lecture_id: uuid.UUID | None = None) -> None:
        if lecture_id is None:
            self._cache.clear()
        else:
            self._cache.pop(lecture_id, None)
        self._rerank_cache.clear()


search_service = SearchService()
