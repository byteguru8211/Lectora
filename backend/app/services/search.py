"""Hybrid semantic search: dense embeddings + full-text + exact technical terms.

Pipeline
--------
1. Dense recall   — cosine similarity over cached bge-m3 chunk vectors, calibrated
                    against the corpus (z-score) so "best of a bad lot" stays low.
2. Lexical recall — ``websearch_to_tsquery('russian', ...)`` + ``ts_rank_cd``.
3. Exact evidence — IDF-weighted coverage of technical terms (C++, C#, .NET):
                    full-text search drops their punctuation, embeddings cannot
                    tell C++ from Java, so they are matched literally.
4. Fusion         — dense/lexical support gated by exact-term coverage.
5. Rerank         — bge-reranker-v2-m3 re-scores a window around the match.
6. De-duplicate   — near-by hits from the same lecture are collapsed.
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
from ..utils.text import (
    highlight_spans,
    is_technical_atom,
    query_terms,
    snippet,
    technical_pattern,
)
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


def dense_relevance(dense: np.ndarray) -> np.ndarray:
    """Calibrate raw cosine similarities against this corpus.

    Min-max scaling always turns the best chunk into 1.0, even when the query
    matches nothing.  A z-score with a floor keeps weak matches weak.
    """
    if dense.size == 0:
        return dense
    spread = float(dense.std())
    if spread < 1e-6:
        return np.zeros_like(dense)
    z = (dense - float(dense.mean())) / spread
    floor = Config.SEARCH_DENSE_Z_FLOOR
    span = max(Config.SEARCH_DENSE_Z_SPAN, 1e-6)
    return np.clip((z - floor) / span, 0.0, 1.0)


def lexical_relevance(scores: np.ndarray) -> np.ndarray:
    saturation = max(Config.SEARCH_LEX_SATURATION, 1e-6)
    return np.clip(scores / saturation, 0.0, 1.0)


def term_coverage(meta: list[dict], terms: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """IDF-weighted share of technical terms found in a chunk or its lecture title.

    Rare terms dominate the coverage; a term absent from the whole corpus gets
    the highest IDF and therefore zero coverage for every chunk.
    """
    count = len(meta)
    if not terms or not count:
        return np.zeros(count, dtype=np.float32), np.zeros(0, dtype=np.float32)
    matched = np.zeros((len(terms), count), dtype=np.float32)
    for row, term in enumerate(terms):
        pattern = technical_pattern(term)
        for col, item in enumerate(meta):
            if pattern.search(item["title_cf"]) or pattern.search(item["text_cf"]):
                matched[row, col] = 1.0
    df = matched.sum(axis=1)
    idf = np.log((count + 1.0) / (df + 1.0)) + 1.0
    return (idf @ matched) / idf.sum(), df


def title_coverage(meta: list[dict], terms: list[str]) -> np.ndarray:
    """Share of query terms present in the lecture title (inflected forms included)."""
    count = len(meta)
    if not terms or not count:
        return np.zeros(count, dtype=np.float32)
    by_title: dict[str, float] = {}
    coverage = np.zeros(count, dtype=np.float32)
    for index, item in enumerate(meta):
        title = item["title_cf"]
        if title not in by_title:
            hits = sum(1 for term in terms if highlight_spans(title, [term]))
            by_title[title] = hits / len(terms)
        coverage[index] = by_title[title]
    return coverage


def fuse_scores(
    dense_rel: np.ndarray,
    lex_rel: np.ndarray,
    title_cov: np.ndarray,
    coverage: np.ndarray | None,
) -> np.ndarray:
    weight = Config.SEARCH_LEXICAL_WEIGHT
    support = (1.0 - weight) * dense_rel + weight * lex_rel
    if coverage is None:
        return np.clip(support + 0.12 * title_cov, 0.0, 1.0)
    # A chunk without the requested technology cannot be a strong hit, no
    # matter how "close" its embedding is.  Coverage dominates, but the
    # remaining support still ranks chunks inside the matching lectures.
    return np.clip(0.55 * coverage + 0.35 * support + 0.10 * title_cov, 0.0, 1.0)


def blend_final(fused: float, rerank_score: float | None) -> float:
    """Reranking adjusts confidence; retrieval relevance stays the base.

    ``CrossEncoder.predict`` already applies sigmoid, so scores are probabilities.
    The factor is bounded, so an undecided reranker (ASR writes "пайтон" instead
    of "Python") cannot erase a solid retrieval hit.
    """
    if rerank_score is None:
        return 0.7 * fused
    return min(1.0, fused * (0.7 + 0.6 * float(rerank_score)))


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
                        "text_cf": record.text.casefold(),
                        "title_cf": (lecture.title or "").casefold(),
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
        dense_rel = dense_relevance(dense)

        terms = query_terms(query)
        tech_terms = [term for term in terms if is_technical_atom(term)]
        plain_query = " ".join(term for term in terms if not is_technical_atom(term))

        chunk_ids = [item["chunk_id"] for item in meta]
        lexical = self._lexical_scores(session, plain_query, chunk_ids) if plain_query else {}
        lex_raw = np.array(
            [lexical.get(chunk_id, 0.0) for chunk_id in chunk_ids], dtype=np.float32
        )
        lex_rel = lexical_relevance(lex_raw)

        coverage = None
        if tech_terms:
            coverage, _ = term_coverage(meta, tech_terms)

        fused = fuse_scores(dense_rel, lex_rel, title_coverage(meta, terms), coverage)

        eligible = np.ones(len(meta), dtype=bool)
        if coverage is not None:
            eligible &= coverage >= 0.2
        candidate_count = int(min(eligible.sum(), Config.SEARCH_CANDIDATES))
        if candidate_count == 0:
            took_ms = int((time.perf_counter() - started) * 1000)
            log.info(
                "search %r -> no candidates (tech=%s) in %d ms", query, tech_terms, took_ms
            )
            return SearchOutcome([], False, took_ms, 0)
        positions = np.flatnonzero(eligible)
        order = positions[np.argsort(fused[positions])[::-1][:candidate_count]]

        hits: list[SearchHit] = []
        for position in order:
            item = meta[int(position)]
            scores = {
                "dense": float(dense[int(position)]),
                "lexical": float(lex_raw[int(position)]),
                "fused": float(fused[int(position)]),
            }
            if coverage is not None:
                scores["exact"] = float(coverage[int(position)])
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
                    scores=scores,
                )
            )

        reranked = False
        if use_rerank and Config.RERANKER_ENABLED and len(hits) > 1:
            window = min(len(hits), max(8, Config.RERANKER_TOP_K))
            head = hits[:window]
            scores = self._rerank_scores(query, head, terms)
            if scores is not None:
                reranked = True
                for hit in head:
                    hit.scores["rerank"] = scores[hit.chunk_id]
                    hit.scores["final"] = blend_final(
                        hit.scores["fused"], scores[hit.chunk_id]
                    )
                # Non-reranked candidates stay below every reranked hit.
                tail_cap = max(0.0, min(hit.scores["final"] for hit in head) - 1e-3)
                for hit in hits[window:]:
                    hit.scores["final"] = min(0.7 * hit.scores["fused"], tail_cap)
                hits.sort(key=lambda item: item.scores["final"], reverse=True)
        if not reranked:
            for hit in hits:
                hit.scores["final"] = hit.scores["fused"]

        popular: list[SearchHit] = []
        for hit in hits:
            if hit.scores["final"] < Config.SEARCH_MIN_SCORE:
                continue
            if not self._is_distinct(hit, popular):
                continue
            spans = highlight_spans(hit.text, terms)
            hit.spans = spans
            hit.snippet, hit.spans = snippet(hit.text, spans, limit=340)
            popular.append(hit)
            if len(popular) >= limit:
                break

        took_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "search %r -> %d hits (%d candidates) in %d ms%s%s",
            query,
            len(popular),
            len(meta),
            took_ms,
            " +rerank" if reranked else "",
            f" tech={tech_terms}" if tech_terms else "",
        )
        return SearchOutcome(popular, reranked, took_ms, len(meta))

    def _rerank_scores(
        self, query: str, hits: list[SearchHit], terms: list[str]
    ) -> dict[int, float] | None:
        """Rerank with an LRU cache: demo-friendly and stable under repeat queries."""
        key = (query.strip().lower(), tuple(hit.chunk_id for hit in hits))
        cached = self._rerank_cache.get(key)
        if cached is not None:
            self._rerank_cache.move_to_end(key)
            return cached
        passages = [self._rerank_passage(hit.text, terms) for hit in hits]
        scores = reranker.rerank(query, passages)
        if scores is None or len(scores) != len(hits):
            return None
        mapping = {hit.chunk_id: float(score) for hit, score in zip(hits, scores)}
        self._rerank_cache[key] = mapping
        if len(self._rerank_cache) > self._rerank_cache_limit:
            self._rerank_cache.popitem(last=False)
        return mapping

    @staticmethod
    def _rerank_passage(text: str, terms: list[str], limit: int = 420) -> str:
        """Feed the reranker a window around the match instead of the chunk head."""
        spans = highlight_spans(text, terms)
        if not spans:
            return text[:limit]
        passage, _ = snippet(text, spans, limit=limit)
        return passage

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
