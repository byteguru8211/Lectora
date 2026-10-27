"""Unit tests for the topic recommendation engine (no database needed)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.recommendations import (
    KIND_KEYWORD,
    KIND_SUBJECT,
    KIND_TOPIC,
    InterestContribution,
    TopicCandidate,
    build_interest_points,
    contributions_for,
    popular_candidates,
    rank_candidates,
    topic_key,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def candidate(
    id: str,
    *,
    subject: str | None = None,
    topic: str | None = None,
    keywords: tuple[str, ...] = (),
    views: int = 0,
    age_days: int = 1,
) -> TopicCandidate:
    return TopicCandidate(
        id=id,
        title=f"lecture {id}",
        subject=subject,
        topic=topic,
        keywords=keywords,
        view_count=views,
        created_at=NOW - timedelta(days=age_days),
    )


def test_topic_key_normalises_case_inflection_and_noise():
    assert topic_key("Программирование") == topic_key("программирования")
    assert topic_key("C++") == topic_key("c++")
    assert topic_key("  Функторы   в C++ ") == topic_key("функторы c++")
    assert topic_key("") == ""


def test_upload_contributions_are_weighted_and_deduplicated():
    lecture = candidate(
        "1",
        subject="Программирование",
        topic="Функторы в C++",
        keywords=("C++", "функторы", "лямбда", "C++"),
    )
    points = contributions_for(lecture, "upload")
    by_kind = {point.kind: point for point in points}
    assert by_kind[KIND_SUBJECT].weight == 5.0
    assert by_kind[KIND_TOPIC].weight == 3.5
    assert by_kind[KIND_KEYWORD].weight == 0.9
    assert len([point for point in points if point.kind == KIND_KEYWORD]) == 3
    labels = [point.label for point in points if point.kind == KIND_KEYWORD]
    assert labels.count("C++") == 1


def test_view_signal_is_weaker_than_upload():
    lecture = candidate("1", subject="История", topic="Древний Рим")
    upload = next(p for p in contributions_for(lecture, "upload") if p.kind == KIND_SUBJECT)
    view = next(p for p in contributions_for(lecture, "view") if p.kind == KIND_SUBJECT)
    assert view.weight < upload.weight


def test_interest_points_merge_same_topic_and_cap_weight():
    contributions = [
        InterestContribution(KIND_SUBJECT, "Программирование", 5.0)
        for _ in range(10)
    ]
    points = build_interest_points(contributions)
    assert len(points) == 1
    assert points[0].weight == 20.0


def test_interest_points_keep_kinds_separate():
    points = build_interest_points(
        [
            InterestContribution(KIND_SUBJECT, "Математика", 5.0),
            InterestContribution(KIND_KEYWORD, "Математика", 0.9),
        ]
    )
    assert {point.kind for point in points} == {KIND_SUBJECT, KIND_KEYWORD}


def profile_for_cpp():
    lecture = candidate(
        "own",
        subject="Программирование",
        topic="Функторы в C++",
        keywords=("C++", "функторы", "лямбда"),
    )
    return build_interest_points(contributions_for(lecture, "upload"))


def test_rank_prefers_specific_topic_over_broad_subject():
    candidates = [
        candidate("topic", subject="Математика", topic="Функторы в C++", views=5),
        candidate("subject", subject="Программирование", topic="ООП", views=5),
        candidate("unrelated", subject="История", topic="Древний Рим", views=500),
    ]
    ranked = rank_candidates(profile_for_cpp(), candidates, limit=5, now=NOW)
    ids = [item.candidate.id for item in ranked]
    assert ids.index("topic") < ids.index("subject")
    assert ranked[0].matched_topics
    assert "Функторы" in ranked[0].reason


def test_rank_excludes_unrelated_from_personalised_part():
    candidates = [
        candidate("cpp", subject="Программирование", topic="Шаблоны C++", views=1),
        candidate("history", subject="История", topic="Рим", views=100),
    ]
    ranked = rank_candidates(profile_for_cpp(), candidates, limit=5, now=NOW)
    assert ranked[0].candidate.id == "cpp"
    assert ranked[0].personalized is True
    history = next(item for item in ranked if item.candidate.id == "history")
    assert history.personalized is False
    assert history.reason == "Популярное на платформе"


def test_rank_fills_short_personalised_feed_with_popular_items():
    candidates = [candidate(f"cpp-{i}", subject="Программирование", views=i) for i in range(2)]
    candidates += [candidate(f"pop-{i}", subject="История", views=50 + i) for i in range(5)]
    ranked = rank_candidates(profile_for_cpp(), candidates, limit=6, now=NOW)
    assert len(ranked) == 6
    assert sum(1 for item in ranked if item.personalized) == 2
    assert ranked[-1].personalized is False


def test_rank_without_matches_returns_popular_feed():
    profile = build_interest_points(
        [InterestContribution(KIND_SUBJECT, "Квантовая физика", 5.0)]
    )
    candidates = [
        candidate("a", subject="История", views=10),
        candidate("b", subject="История", views=80),
    ]
    ranked = rank_candidates(profile, candidates, limit=4, now=NOW)
    assert [item.candidate.id for item in ranked] == ["b", "a"]
    assert all(not item.personalized for item in ranked)


def test_popular_candidates_sort_by_views_and_freshness():
    candidates = [
        candidate("old-popular", views=100, age_days=400),
        candidate("new-quiet", views=1, age_days=0),
        candidate("new-popular", views=100, age_days=1),
    ]
    ranked = popular_candidates(candidates, limit=3, now=NOW)
    assert ranked[0].candidate.id == "new-popular"
    assert ranked[0].score == 1.0
    assert {item.candidate.id for item in ranked} == {"old-popular", "new-quiet", "new-popular"}


def test_keyword_inflection_matches_topic_across_forms():
    profile = build_interest_points(
        [InterestContribution(KIND_KEYWORD, "функторы", 0.9)]
    )
    candidates = [
        candidate("c", subject="C++", topic="Функтор и оператор вызова"),
    ]
    ranked = rank_candidates(profile, candidates, limit=2, now=NOW)
    assert ranked[0].candidate.id == "c"
    assert ranked[0].personalized is True


def test_legacy_lecture_without_classification_uses_keywords():
    legacy = SimpleNamespace(
        id="legacy",
        title="Old",
        subject=None,
        topic=None,
        keywords=["алгоритмы", "сортировка"],
        view_count=0,
        created_at=None,
    )
    candidate_from_legacy = TopicCandidate.from_lecture(legacy)
    assert candidate_from_legacy.subject == "алгоритмы"
    assert candidate_from_legacy.topic == "сортировка"
    assert candidate_from_legacy.keywords == ("алгоритмы", "сортировка")
