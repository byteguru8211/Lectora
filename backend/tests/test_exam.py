"""Exam sheet: deterministic extraction and cache fingerprints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models import Lecture, Section
from app.services.exam import (
    _build_digest,
    _extract_definitions,
    _extract_formulas,
    _fallback_tickets,
    _fingerprint,
    _is_meaningful_formula,
    _LectureMaterial,
    sheet_payload,
)


def _lecture(title: str = "Интегралы", summary: str | None = None, questions=None) -> Lecture:
    lecture = Lecture(
        id=uuid.uuid4(),
        storage_key="k",
        title=title,
        summary=summary,
        questions=questions or [],
    )
    return lecture


def _section(lecture: Lecture, idx: int, title: str, summary: str, details: str = "") -> Section:
    return Section(
        lecture_id=lecture.id,
        idx=idx,
        title=title,
        summary=summary,
        details=details,
        start_sec=idx * 60.0,
        end_sec=idx * 60.0 + 60.0,
        key_points=["Первый тезис", "Второй тезис"],
    )


def _material(lecture: Lecture, *sections: Section) -> _LectureMaterial:
    return _LectureMaterial(lecture=lecture, sections=list(sections), digest="")


def test_extract_definitions_from_notes():
    lecture = _lecture()
    section = _section(
        lecture,
        0,
        "Определение интеграла",
        "Интеграл — это предел интегральных сумм. Функция называется интегрируемой, если предел существует.",
    )
    items = _extract_definitions([_material(lecture, section)])
    terms = {item["term"].lower() for item in items}
    definitions = " ".join(item["definition"] for item in items)
    assert any("интеграл" in term for term in terms)
    assert "интегрируемой" in definitions
    assert all(item["lecture_id"] == str(lecture.id) for item in items)
    assert items[0]["timestamp"] == "0:00"


def test_extract_formulas_from_latex_and_symbols():
    lecture = _lecture()
    section = _section(
        lecture,
        1,
        "Формула Ньютона — Лейбница",
        r"Работает формула $S = \int_a^b f(x)\,dx$. Также $F(b) - F(a) = \int_a^b f(x)dx$.",
        details=r"\[ \frac{d}{dx}F(x) = f(x) \]",
    )
    items = _extract_formulas([_material(lecture, section)])
    formulas = " ".join(item["formula"] for item in items)
    assert r"\int_a^b" in formulas
    assert r"\frac{d}{dx}" in formulas
    assert all(item["start_sec"] == 60.0 for item in items)


def test_fallback_tickets_use_questions_and_points():
    lecture = _lecture("Пределы", questions=["Что такое предел функции?"])
    section = _section(lecture, 0, "Предел", "Предел описывает поведение функции.")
    tickets = _fallback_tickets([_material(lecture, section)])
    assert tickets[0]["question"] == "Что такое предел функции?"
    assert "Первый тезис" in tickets[0]["answer"]
    assert tickets[0]["lecture_id"] == str(lecture.id)


def test_extraction_skips_noise():
    assert not _is_meaningful_formula("2x, 2x + 5, 2x − 5")
    assert _is_meaningful_formula(r"\int_a^b f(x)\,dx")

    lecture = _lecture()
    section = _section(
        lecture,
        0,
        "Сумма Римана",
        "Сумма площадей прямоугольников называется суммой Римана. Предел — это число, к которому стремится сумма Римана.",
    )
    items = _extract_definitions([_material(lecture, section)])
    terms = [item["term"].lower() for item in items]
    assert "предел" in terms
    assert all(item["term"] != "Сумма площадей прямоугольников" for item in items)


def test_fingerprint_does_not_depend_on_prompt_budget():
    lecture = _lecture(summary="Кратко")
    section = _section(lecture, 0, "Раздел", "Содержание", details="Подробности")
    material = _material(lecture, section)

    _build_digest([material], 24_000)
    api_fingerprint = _fingerprint([material])
    _build_digest([material], 700)
    local_fingerprint = _fingerprint([material])

    assert api_fingerprint == local_fingerprint

    section.summary = "Изменённое содержание"
    assert _fingerprint([material]) != api_fingerprint


def test_fingerprint_ignores_lecture_counters():
    lecture = _lecture(summary="Кратко")
    material = _material(lecture, _section(lecture, 0, "Раздел", "Содержание"))
    before = _fingerprint([material])

    lecture.updated_at = datetime.now(timezone.utc)
    lecture.view_count = 42
    lecture.search_hits = 7
    lecture.llm_mode_used = "offline"

    assert _fingerprint([material]) == before


def test_missing_sheet_payload():
    payload = sheet_payload(None, fingerprint="abc", lecture_count=2)
    assert payload["status"] == "missing"
    assert payload["lecture_count"] == 2
    assert payload["tickets"] == []
