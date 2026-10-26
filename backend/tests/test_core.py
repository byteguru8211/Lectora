"""Fast unit tests that do not require models or a database."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.chunker import TimedText, build_chunks
from app.services.summarizer import Summarizer
from app.services.asr import Segment
from app.utils.text import (
    highlight_spans,
    keywords,
    query_terms,
    restore_punctuation,
    split_sentences,
    truncate,
)
from app.utils.timefmt import format_timestamp, parse_timestamp, vtt_time


def test_format_timestamp():
    assert format_timestamp(0) == "0:00"
    assert format_timestamp(95) == "1:35"
    assert format_timestamp(3725) == "1:02:05"


def test_parse_timestamp_roundtrip():
    assert parse_timestamp("1:02:05") == 3725
    assert parse_timestamp("1:35") == 95
    assert parse_timestamp("0:00:10.500") == 10.5


def test_vtt_time():
    assert vtt_time(62.5) == "00:01:02.500"


def test_restore_punctuation_capitalises_and_adds_period():
    text = restore_punctuation("прямоугольный параллелепипед это многогранник", end=".")
    assert text[0].isupper()
    assert text.endswith(".")


def test_restore_punctuation_handles_fillers():
    text = restore_punctuation("э вот это куб", end=".")
    assert "э" not in text.split()


def test_split_sentences():
    parts = split_sentences("Первое. Второе! Третье?")
    assert parts == ["Первое.", "Второе!", "Третье?"]


def test_keywords_ignore_stopwords():
    result = keywords(
        [
            "куб это прямоугольный параллелепипед",
            "объём куба равен произведению рёбер",
        ],
        limit=6,
    )
    assert "куб" in result or "куба" in result
    assert "это" not in result


def test_highlight_spans_find_inflected_words():
    text = "Формула объёма конуса выводится через интеграл"
    spans = highlight_spans(text, ["объём", "конус"])
    assert spans
    assert any("объёма" in text[span["start"] : span["end"]] for span in spans)


def test_query_terms_drops_stopwords():
    assert "теоремы" in query_terms("объяснение теоремы пифагора")
    assert "и" not in query_terms("теорема и доказательство")


def test_truncate_keeps_word_boundary():
    result = truncate("слово " * 100, 20)
    assert len(result) <= 21
    assert result.endswith("…")


def test_build_chunks_respects_limits():
    segments = [
        TimedText(start_sec=i * 5, end_sec=i * 5 + 4.5, text="слово " * 20)
        for i in range(40)
    ]
    chunks = build_chunks(segments, max_chars=400, max_sec=40, overlap_segments=1)
    assert chunks
    assert all(len(chunk.text) <= 460 for chunk in chunks)
    assert all(chunk.end_sec - chunk.start_sec <= 50 for chunk in chunks)
    assert chunks[0].start_sec == 0


def test_build_chunks_overlap_keeps_context():
    segments = [
        TimedText(start_sec=float(i * 4), end_sec=float(i * 4 + 3), text=f"чанк {i}")
        for i in range(20)
    ]
    chunks = build_chunks(segments, max_chars=30, max_sec=100, overlap_segments=1)
    assert len(chunks) >= 2
    assert chunks[1].start_sec <= chunks[0].end_sec


def test_build_chunks_empty():
    assert build_chunks([]) == []


def test_extractive_summary_has_sections_and_keywords():
    summarizer = Summarizer()
    segments = [
        Segment(start_sec=0, end_sec=5, text="Сегодня разберём теорему пифагора."),
        Segment(start_sec=5, end_sec=12, text="Квадрат гипотенузы равен сумме квадратов катетов."),
        Segment(start_sec=12, end_sec=20, text="Докажем это через площади треугольников."),
        Segment(start_sec=20, end_sec=30, text="Теорема пифагора полезна в геометрии."),
        Segment(start_sec=30, end_sec=40, text="Пример: египетский треугольник со сторонами три четыре пять."),
    ]
    notes = summarizer._extractive(title="Пифагор", segments=segments, duration=40)
    assert notes.summary
    assert notes.sections
    assert notes.keywords
    assert notes.sections[-1].end_sec <= 41


def test_validate_extracts_clean_title():
    summarizer = Summarizer()
    summary = " ".join(["слово"] * 60)
    data = {
        "title": ' «Прямоугольный параллелепипед и тела вращения». ',
        "summary": summary,
        "sections": [
            {"title": f"Раздел {index}", "start_sec": index * 60, "end_sec": index * 60 + 60}
            for index in range(3)
        ],
        "keywords": ["куб", "сфера", "конус"],
    }
    notes = summarizer._validate(data, 200)
    assert notes is not None
    assert notes.title == "Прямоугольный параллелепипед и тела вращения"
    assert len(notes.sections) == 3


def test_validate_rejects_tiny_title():
    summarizer = Summarizer()
    data = {
        "title": "…",
        "summary": " ".join(["слово"] * 60),
        "sections": [{"title": "Раздел", "start_sec": 0, "end_sec": 60}],
        "keywords": [],
    }
    notes = summarizer._validate(data, 60)
    assert notes is not None
    assert notes.title is None
