"""Ranking primitives: calibration, exact-term gating and rerank blending."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.search import blend_final, dense_relevance, fuse_scores, term_coverage, title_coverage
from app.utils.text import (
    highlight_spans,
    is_technical_atom,
    query_terms,
    technical_pattern,
)


def test_query_terms_keep_technical_punctuation():
    assert query_terms("C++") == ["c++"]
    assert query_terms("C++ указатели") == ["c++", "указатели"]
    assert query_terms("C#") == ["c#"]
    assert query_terms("node.js") == ["node.js"]
    assert "c" not in query_terms("C++")


def test_query_aliases_normalise_phonetic_spellings():
    assert query_terms("си плюс плюс") == ["c++"]
    assert query_terms("cpp") == ["c++"]
    assert query_terms("си шарп") == ["c#"]


def test_technical_pattern_matches_language_names():
    assert technical_pattern("c++").search("серия мини уроков по C++")
    assert technical_pattern("c++").search("изучаем C++11")
    # Vosk writes "C++" phonetically; the alias has to survive ASR.
    assert technical_pattern("c++").search("начинаю серию по всей плюс плюс")
    assert technical_pattern("c#").search("пишем на C#")
    assert technical_pattern(".net").search("платформа .NET")
    assert not technical_pattern("c++").search("программа на java")


def test_is_technical_atom():
    assert is_technical_atom("c++")
    assert is_technical_atom("c#")
    assert is_technical_atom(".net")
    assert not is_technical_atom("python")
    assert not is_technical_atom("функтор")


def test_highlight_spans_mark_whole_technical_token():
    text = "Начинаю серию мини уроков по C++ и C# сегодня"
    spans = highlight_spans(text, ["c++", "c#"])
    marked = [text[span["start"] : span["end"]] for span in spans]
    assert marked == ["C++", "C#"]


def test_dense_relevance_does_not_promote_noise():
    uniform = np.full(8, 0.37, dtype=np.float32)
    assert np.all(dense_relevance(uniform) == 0.0)

    noise = np.array([0.37, 0.38, 0.36, 0.37, 0.37, 0.38, 0.37, 0.39], dtype=np.float32)
    calibrated = dense_relevance(noise)
    assert calibrated.max() <= 0.3  # being "first of a bad lot" stays weak

    strong = np.array([0.37, 0.38, 0.36, 0.37, 0.37, 0.38, 0.37, 0.70], dtype=np.float32)
    assert dense_relevance(strong)[-1] > 0.5


def test_term_coverage_uses_titles_and_idf():
    meta = [
        {"title_cf": "функторы в c++", "text_cf": "сегодня разберём функторы"},
        {"title_cf": "java: язык программирования", "text_cf": "джава с нуля"},
    ]
    coverage, df = term_coverage(meta, ["c++"])
    assert coverage.tolist() == [1.0, 0.0]
    assert df.tolist() == [1.0]

    # A term absent from the corpus has no coverage anywhere.
    missing, _ = term_coverage(meta, [".net"])
    assert missing.tolist() == [0.0, 0.0]


def test_fuse_scores_gates_chunks_without_the_term():
    dense = np.array([0.8, 0.9], dtype=np.float32)
    lex = np.zeros(2, dtype=np.float32)
    title = np.array([1.0, 0.0], dtype=np.float32)
    coverage = np.array([1.0, 0.0], dtype=np.float32)
    fused = fuse_scores(dense, lex, title, coverage)
    # The second chunk is "closer" per embeddings yet has no C++ anywhere.
    assert fused[0] > fused[1] + 0.5


def test_title_coverage_handles_inflection():
    meta = [
        {"title_cf": "функторы в c++"},
        {"title_cf": "java: язык программирования"},
    ]
    assert title_coverage(meta, ["функтор"]).tolist() == [1.0, 0.0]


def test_blend_final_keeps_retrieval_as_base():
    assert blend_final(0.8, None) == 0.8 * 0.7
    assert blend_final(0.8, 0.0) == 0.8 * 0.7
    assert blend_final(0.8, 1.0) == 1.0
    # An undecided reranker must not erase a solid hit.
    assert blend_final(0.8, 0.02) > 0.5
