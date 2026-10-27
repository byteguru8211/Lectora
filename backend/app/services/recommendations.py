"""Topic-based recommendations for the public catalogue.

The engine is deliberately model-free at request time: notes already provide
``subject``, ``topic`` and ``keywords``, so ranking is a deterministic scoring
problem instead of another LLM call.

Pipeline
--------
1. Every ready upload and every public view contributes topic points
   (subject, topic, keyword stems) to a *materialised* profile in
   ``user_interests``.  The profile is rebuilt from sources, never patched
   incrementally, so edits, re-classification and deletions stay consistent.
2. Candidates are public ready lectures the user does not own.
3. Matching compares normalised stem sets; a specific topic outweighs a broad
   subject, keywords break ties. Popularity and freshness only nudge equal
   topical matches.
4. A user without a profile (or without matches) gets the popular feed, clearly
   marked as such by ``mode``.

All pure helpers are stateless and covered by unit tests without a database.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import Lecture, LectureView, User, UserInterest, VideoGroup, utcnow
from ..utils.text import STOPWORDS

log = logging.getLogger(__name__)

KIND_SUBJECT = "subject"
KIND_TOPIC = "topic"
KIND_KEYWORD = "keyword"
KINDS = (KIND_SUBJECT, KIND_TOPIC, KIND_KEYWORD)

SOURCE_UPLOAD = "upload"
SOURCE_VIEW = "view"

# A user's own lecture is a strong signal of interest; a single view is weaker.
SOURCE_WEIGHTS = {
    SOURCE_UPLOAD: {KIND_SUBJECT: 5.0, KIND_TOPIC: 3.5, KIND_KEYWORD: 0.9},
    SOURCE_VIEW: {KIND_SUBJECT: 2.0, KIND_TOPIC: 1.5, KIND_KEYWORD: 0.35},
}
SOURCE_KEYWORD_LIMIT = {SOURCE_UPLOAD: 8, SOURCE_VIEW: 5}

# Per-point caps keep a large personal library from drowning every other topic.
MAX_POINT_WEIGHT = 20.0
MAX_PROFILE_POINTS = 40
MIN_PERSONALIZED_ITEMS = 4
CANDIDATE_LIMIT = 300
DEFAULT_LIMIT = 12

_WORD_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)


def _tokens(text: str) -> frozenset[str]:
    words = _WORD_RE.findall((text or "").lower().replace("ё", "е"))
    return frozenset(
        _stem(word)
        for word in words
        if word not in STOPWORDS and (len(word) > 1 or word == "c")
    )


def _stem(token: str) -> str:
    """Crude but effective Russian stem for matching inflected forms."""
    return token[:6] if len(token) > 5 else token


def topic_key(text: str) -> str:
    """Normalise a phrase into a stable, stem-based key."""
    return " ".join(sorted(_tokens(text)))


def _tokens_of_key(key: str) -> frozenset[str]:
    return frozenset(key.split()) if key else frozenset()


def _sets_match(point: frozenset[str], candidate: frozenset[str]) -> bool:
    """True when one phrase is contained in the other (inflection tolerant)."""
    if not point or not candidate:
        return False
    return point <= candidate or candidate <= point


@dataclass(frozen=True)
class TopicCandidate:
    """Everything the ranker needs to know about one video."""

    id: str
    title: str
    subject: str | None = None
    topic: str | None = None
    keywords: tuple[str, ...] = ()
    view_count: int = 0
    created_at: datetime | None = None

    @classmethod
    def from_lecture(cls, lecture: Lecture) -> "TopicCandidate":
        keywords = tuple(
            str(item).strip()
            for item in (lecture.keywords or [])
            if str(item).strip()
        )
        # Legacy rows may predate automatic classification: derive sensible
        # topics from the generated keywords instead of dropping the signal.
        subject = (lecture.subject or "").strip() or (keywords[0] if keywords else None)
        topic = (lecture.topic or "").strip() or (
            keywords[1] if len(keywords) > 1 else None
        )
        if topic and topic_key(topic) == topic_key(subject or ""):
            topic = None
        return cls(
            id=str(lecture.id),
            title=lecture.title,
            subject=subject,
            topic=topic,
            keywords=keywords,
            view_count=int(lecture.view_count or 0),
            created_at=lecture.created_at,
        )


@dataclass(frozen=True)
class InterestContribution:
    kind: str
    label: str
    weight: float


@dataclass(frozen=True)
class InterestPoint:
    key: str
    label: str
    kind: str
    weight: float

    @property
    def tokens(self) -> frozenset[str]:
        return _tokens_of_key(self.key)


def contributions_for(candidate: TopicCandidate, source: str) -> list[InterestContribution]:
    """Turn one lecture into weighted topic points for a given signal."""
    weights = SOURCE_WEIGHTS.get(source)
    if weights is None:
        raise ValueError(f"unknown interest source: {source!r}")
    limit = SOURCE_KEYWORD_LIMIT[source]
    items: list[InterestContribution] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, label: str | None, weight: float) -> None:
        label = " ".join((label or "").split())
        key = topic_key(label)
        if not key or (kind, key) in seen:
            return
        seen.add((kind, key))
        items.append(InterestContribution(kind=kind, label=label, weight=weight))

    subject_key = topic_key(candidate.subject or "")
    add(KIND_SUBJECT, candidate.subject, weights[KIND_SUBJECT])
    add(KIND_TOPIC, candidate.topic, weights[KIND_TOPIC])
    for keyword in candidate.keywords[:limit]:
        if topic_key(keyword) == subject_key:
            continue
        add(KIND_KEYWORD, keyword, weights[KIND_KEYWORD])
    return items


def build_interest_points(
    contributions: list[InterestContribution],
    *,
    limit: int = MAX_PROFILE_POINTS,
) -> list[InterestPoint]:
    """Aggregate contributions by ``(kind, key)`` and cap runaway weights."""
    merged: dict[tuple[str, str], InterestPoint] = {}
    for item in contributions:
        key = topic_key(item.label)
        if not key:
            continue
        slot = (item.kind, key)
        current = merged.get(slot)
        weight = min(MAX_POINT_WEIGHT, (current.weight if current else 0.0) + item.weight)
        merged[slot] = InterestPoint(
            key=key,
            label=current.label if current else item.label,
            kind=item.kind,
            weight=weight,
        )
    ordered = sorted(merged.values(), key=lambda point: point.weight, reverse=True)
    return ordered[:limit]


@dataclass(frozen=True)
class RankedCandidate:
    candidate: TopicCandidate
    score: float
    topical: float
    reason: str
    matched_topics: tuple[str, ...]
    personalized: bool


def _freshness(created_at: datetime | None, now: datetime) -> float:
    if created_at is None:
        return 0.0
    value = created_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - value).total_seconds() / 86400.0)
    return 0.5 ** (age_days / 90.0)


def _popularity(view_count: int) -> float:
    return min(1.0, math.log1p(max(0, view_count)) / 6.0)


def _trend_score(candidate: TopicCandidate, now: datetime) -> float:
    return _popularity(candidate.view_count) + 0.5 * _freshness(candidate.created_at, now)


def _match_points(
    candidate_tokens: frozenset[str],
    points: list[InterestPoint],
    factor: float,
    *,
    take: int = 3,
) -> tuple[float, list[InterestPoint]]:
    hits = [
        point
        for point in points
        if _sets_match(_tokens_of_key(point.key), candidate_tokens)
    ]
    hits.sort(key=lambda point: point.weight, reverse=True)
    hits = hits[:take]
    return sum(point.weight for point in hits) * factor, hits


def _keyword_score(
    candidate: TopicCandidate,
    points: list[InterestPoint],
    factor: float,
    *,
    take: int = 3,
) -> tuple[float, list[InterestPoint]]:
    keyword_sets = [
        tokens
        for tokens in (_tokens(keyword) for keyword in candidate.keywords)
        if tokens
    ]
    hits: list[InterestPoint] = []
    for point in points:
        if any(_sets_match(_tokens_of_key(point.key), tokens) for tokens in keyword_sets):
            hits.append(point)
    hits.sort(key=lambda point: point.weight, reverse=True)
    hits = hits[:take]
    return sum(point.weight for point in hits) * factor, hits


def _score(
    profile_by_kind: dict[str, list[InterestPoint]],
    candidate: TopicCandidate,
) -> tuple[float, list[str]]:
    """Return ``(topical_score, matched_labels)`` for one candidate."""
    subject_tokens = _tokens(candidate.subject or "")
    topic_tokens = _tokens(candidate.topic or "")

    topical = 0.0
    matched: list[InterestPoint] = []

    score, hits = _match_points(topic_tokens, profile_by_kind[KIND_TOPIC], 3.0)
    topical += score
    matched.extend(hits)

    score, hits = _match_points(subject_tokens, profile_by_kind[KIND_SUBJECT], 2.0)
    topical += score
    matched.extend(hits)

    score, hits = _keyword_score(candidate, profile_by_kind[KIND_KEYWORD], 1.0)
    topical += score
    matched.extend(hits)

    # Cross-kind matches: a broad subject still points at a specific topic and
    # vice versa; they count less than a same-kind hit.
    score, hits = _match_points(topic_tokens, profile_by_kind[KIND_SUBJECT], 1.5)
    topical += score
    matched.extend(hits)

    score, hits = _match_points(subject_tokens, profile_by_kind[KIND_TOPIC], 1.5)
    topical += score
    matched.extend(hits)

    for tokens in (subject_tokens, topic_tokens):
        score, hits = _match_points(tokens, profile_by_kind[KIND_KEYWORD], 0.6)
        topical += score
        matched.extend(hits)

    if not matched:
        return 0.0, []

    unique: dict[str, InterestPoint] = {}
    for point in matched:
        unique.setdefault(point.label.lower(), point)
    ordered = sorted(unique.values(), key=lambda point: point.weight, reverse=True)
    labels = [point.label for point in ordered[:3]]
    return topical, labels


def _reason(labels: list[str], *, personalized: bool) -> str:
    if personalized and labels:
        if len(labels) == 1:
            return f"Тема: «{labels[0]}»"
        return "Темы: " + ", ".join(f"«{label}»" for label in labels)
    return "Популярное на платформе"


def rank_candidates(
    profile: list[InterestPoint],
    candidates: list[TopicCandidate],
    *,
    limit: int = DEFAULT_LIMIT,
    now: datetime | None = None,
) -> list[RankedCandidate]:
    """Rank candidates for a profile; falls back to popularity when needed."""
    now = now or datetime.now(timezone.utc)
    limit = max(1, min(limit, 30))

    by_kind: dict[str, list[InterestPoint]] = {kind: [] for kind in KINDS}
    for point in profile:
        by_kind.setdefault(point.kind, []).append(point)

    scored: list[tuple[TopicCandidate, float, float, list[str]]] = []
    if profile:
        for candidate in candidates:
            topical, labels = _score(by_kind, candidate)
            scored.append((candidate, topical, topical, labels))

    personalized = [item for item in scored if item[1] > 0.0]
    personalized.sort(
        key=lambda item: (
            item[1],
            _trend_score(item[0], now),
        ),
        reverse=True,
    )

    chosen: list[RankedCandidate] = []
    chosen_ids: set[str] = set()
    for candidate, topical, _, labels in personalized[:limit]:
        chosen.append(
            RankedCandidate(
                candidate=candidate,
                score=0.0,
                topical=topical,
                reason=_reason(labels, personalized=True),
                matched_topics=tuple(labels),
                personalized=True,
            )
        )
        chosen_ids.add(candidate.id)

    # Personalised feed should not look empty just because the catalogue is
    # small: top up with popular videos, explicitly marked as such.
    if len(chosen) < min(MIN_PERSONALIZED_ITEMS, limit):
        popular = sorted(
            (candidate for candidate in candidates if candidate.id not in chosen_ids),
            key=lambda candidate: _trend_score(candidate, now),
            reverse=True,
        )
        for candidate in popular[: limit - len(chosen)]:
            chosen.append(
                RankedCandidate(
                    candidate=candidate,
                    score=0.0,
                    topical=0.0,
                    reason=_reason([], personalized=False),
                    matched_topics=(),
                    personalized=False,
                )
            )
            chosen_ids.add(candidate.id)

    top = max((item.topical for item in chosen), default=0.0) or 1.0
    return [
        RankedCandidate(
            candidate=item.candidate,
            score=round(item.topical / top, 4) if item.topical else 0.0,
            topical=item.topical,
            reason=item.reason,
            matched_topics=item.matched_topics,
            personalized=item.personalized,
        )
        for item in chosen
    ]


def popular_candidates(
    candidates: list[TopicCandidate],
    *,
    limit: int = DEFAULT_LIMIT,
    now: datetime | None = None,
) -> list[RankedCandidate]:
    """Cold-start feed: most viewed, then freshest."""
    now = now or datetime.now(timezone.utc)
    ordered = sorted(
        candidates,
        key=lambda candidate: _trend_score(candidate, now),
        reverse=True,
    )[: max(1, min(limit, 30))]
    top = max((_trend_score(item, now) for item in ordered), default=0.0) or 1.0
    return [
        RankedCandidate(
            candidate=candidate,
            score=round(_trend_score(candidate, now) / top, 4),
            topical=0.0,
            reason=_reason([], personalized=False),
            matched_topics=(),
            personalized=False,
        )
        for candidate in ordered
    ]


@dataclass(frozen=True)
class RecommendationItem:
    lecture: Lecture
    owner_name: str
    group_name: str | None
    score: float
    reason: str
    matched_topics: tuple[str, ...]
    personalized: bool


@dataclass(frozen=True)
class RecommendationFeed:
    mode: str  # personalized | trending | cold_start
    items: list[RecommendationItem]
    interests: list[InterestPoint]
    fallback: bool


def public_filter():
    return or_(Lecture.visibility == "public", VideoGroup.visibility == "public")


class RecommendationService:
    """Materialises interest profiles and builds the public "For you" feed."""

    def rebuild_profile(self, session: Session, user_id: uuid.UUID) -> list[InterestPoint]:
        own = (
            session.query(Lecture)
            .filter(Lecture.user_id == user_id, Lecture.status == "ready")
            .all()
        )
        viewed = (
            session.query(Lecture)
            .join(LectureView, LectureView.lecture_id == Lecture.id)
            .filter(
                LectureView.user_id == user_id,
                Lecture.status == "ready",
                or_(Lecture.user_id.is_(None), Lecture.user_id != user_id),
            )
            .all()
        )

        contributions: list[InterestContribution] = []
        for lecture in own:
            contributions.extend(contributions_for(TopicCandidate.from_lecture(lecture), SOURCE_UPLOAD))
        for lecture in viewed:
            contributions.extend(contributions_for(TopicCandidate.from_lecture(lecture), SOURCE_VIEW))

        points = build_interest_points(contributions)
        session.query(UserInterest).filter(UserInterest.user_id == user_id).delete(
            synchronize_session=False
        )
        session.flush()
        for point in points:
            session.add(
                UserInterest(
                    user_id=user_id,
                    topic_key=point.key,
                    label=point.label,
                    kind=point.kind,
                    weight=round(point.weight, 3),
                )
            )
        session.flush()
        log.debug("interest profile rebuilt for %s: %d topic(s)", user_id, len(points))
        return points

    def load_profile(self, session: Session, user_id: uuid.UUID) -> list[InterestPoint]:
        rows = (
            session.query(UserInterest)
            .filter(UserInterest.user_id == user_id)
            .order_by(UserInterest.weight.desc())
            .limit(MAX_PROFILE_POINTS)
            .all()
        )
        if rows:
            return [
                InterestPoint(key=row.topic_key, label=row.label, kind=row.kind, weight=row.weight)
                for row in rows
            ]
        # Existing installations get a profile on first visit instead of after
        # the next upload.
        has_own = (
            session.query(func.count(Lecture.id))
            .filter(Lecture.user_id == user_id, Lecture.status == "ready")
            .scalar()
            or 0
        )
        has_views = (
            session.query(func.count(LectureView.id))
            .filter(LectureView.user_id == user_id)
            .scalar()
            or 0
        )
        if not has_own and not has_views:
            return []
        self.rebuild_profile(session, user_id)
        session.commit()
        rows = (
            session.query(UserInterest)
            .filter(UserInterest.user_id == user_id)
            .order_by(UserInterest.weight.desc())
            .limit(MAX_PROFILE_POINTS)
            .all()
        )
        return [
            InterestPoint(key=row.topic_key, label=row.label, kind=row.kind, weight=row.weight)
            for row in rows
        ]

    def recommend(
        self,
        session: Session,
        user_id: uuid.UUID,
        *,
        limit: int = DEFAULT_LIMIT,
    ) -> RecommendationFeed:
        profile = self.load_profile(session, user_id)
        rows = (
            session.query(Lecture, User.name, VideoGroup.name)
            .join(User, User.id == Lecture.user_id)
            .outerjoin(VideoGroup, VideoGroup.id == Lecture.group_id)
            .filter(
                Lecture.status == "ready",
                public_filter(),
                or_(Lecture.user_id.is_(None), Lecture.user_id != user_id),
            )
            .order_by(Lecture.created_at.desc())
            .limit(CANDIDATE_LIMIT)
            .all()
        )
        lectures = {str(lecture.id): (lecture, owner, group) for lecture, owner, group in rows}
        candidates = [TopicCandidate.from_lecture(lecture) for lecture, _, _ in rows]

        if not profile:
            ranked = popular_candidates(candidates, limit=limit)
            mode = "cold_start"
        else:
            ranked = rank_candidates(profile, candidates, limit=limit)
            mode = "personalized" if any(item.personalized for item in ranked) else "trending"

        items: list[RecommendationItem] = []
        for item in ranked:
            entry = lectures.get(item.candidate.id)
            if entry is None:
                continue
            lecture, owner_name, group_name = entry
            items.append(
                RecommendationItem(
                    lecture=lecture,
                    owner_name=owner_name,
                    group_name=group_name,
                    score=item.score,
                    reason=item.reason,
                    matched_topics=item.matched_topics,
                    personalized=item.personalized,
                )
            )
        fallback = bool(profile) and any(not item.personalized for item in items)
        return RecommendationFeed(
            mode=mode,
            items=items,
            interests=profile[:8],
            fallback=fallback,
        )

    def record_view(
        self,
        session: Session,
        user_id: uuid.UUID,
        lecture: Lecture,
    ) -> tuple[bool, int]:
        """Track a public view; interests change only on the first one."""
        view = (
            session.query(LectureView)
            .filter(LectureView.user_id == user_id, LectureView.lecture_id == lecture.id)
            .first()
        )
        first = view is None
        if view is None:
            session.add(LectureView(user_id=user_id, lecture_id=lecture.id, view_count=1))
        else:
            view.view_count = int(view.view_count or 0) + 1
            view.last_viewed_at = utcnow()
        lecture.view_count = int(lecture.view_count or 0) + 1
        session.flush()
        if first and lecture.user_id != user_id:
            self.rebuild_profile(session, user_id)
        return first, lecture.view_count


recommendation_service = RecommendationService()
