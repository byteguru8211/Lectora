"""Exam cheat sheet for a group, merged from lecture notes.

No extra pipeline stage: the sheet is built on demand from notes that already
exist, with one LLM call over a compact digest.  Definitions and formulas are
extracted deterministically as well, so the sheet stays useful when no model
is available.  A fingerprint of the source notes lets the UI show when the
cached sheet went stale.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field

from ..models import ExamSheet, Lecture, Section, VideoGroup
from ..utils.text import normalize_space, truncate
from ..utils.timefmt import format_timestamp, parse_timestamp
from .llm_base import LlmUnavailable
from .llm_modes import MODE_OFFLINE, normalize_mode, resolve_client

log = logging.getLogger(__name__)

MAX_TICKETS = 24
MAX_DEFINITIONS = 30
MAX_FORMULAS = 20
MAX_CHEATSHEET_CHARS = 16_000

# Case-sensitive on purpose: a definition starts with a capitalised term, and
# matching lowercase fragments produces noise like «непрерывной — это значит…».
_DEFINITION_PATTERNS = (
    re.compile(
        r"(?P<term>[A-ZА-ЯЁ][^.!?\n—–-]{2,80}?)\s*[—–-]\s*это\s+(?P<definition>[^.!?\n]{10,320})"
    ),
    re.compile(
        r"(?P<term>[A-ZА-ЯЁ][^.!?\n]{2,80}?)\s+называ(?:ется|ют)\s+(?P<definition>[^.!?\n]{10,320})"
    ),
    re.compile(
        r"Определение\s*[:\-—]\s*(?P<definition>[^.!?\n]{10,320})",
        re.IGNORECASE,
    ),
)

_NON_TERM_STARTS = {
    "он", "она", "оно", "они", "это", "этот", "эта", "эти", "если", "когда",
    "тогда", "также", "поэтому", "например", "значит", "таким", "отсюда",
    "далее", "теперь", "рассмотрим", "пусть", "где", "при", "для", "как",
    "что", "чтобы", "который", "которая", "которые", "есть", "нужно",
    "такой", "такая", "такие", "чем", "в", "на", "из", "по", "с", "у",
}

_FORMULA_COMMANDS = re.compile(
    r"\\(?:int|iint|sum|prod|lim|frac|sqrt|partial|nabla|vec|overline)\b"
)


def _looks_like_term(term: str) -> bool:
    words = re.findall(r"[A-Za-zА-Яа-яЁё]+", term)
    if not words:
        return False
    if words[0].lower() in _NON_TERM_STARTS:
        return False
    if "," in term or " что " in f" {term.lower()} ":
        return False
    return 3 <= len(term) <= 90


def _is_meaningful_formula(tex: str) -> bool:
    value = tex.strip().rstrip(".,;:")
    if re.fullmatch(r"\\[A-Za-z]+", value):
        return False  # a bare command such as «\int» is not a formula
    if re.fullmatch(r"[a-zA-Zа-яА-Я]\s*=\s*[-+\d\s.,a-zA-Z^]+", value) and "\\" not in value and len(value) < 20:
        return False  # a worked example like «x = -3», not a formula
    # «2x, 2x + 5, 2x − 5» is a list, not a formula; commas inside f(x, y)
    # are fine and disappear together with their brackets.
    top_level = re.sub(r"\\[,;:!]", "", value)  # LaTeX spacing, e.g. «\,»
    top_level = re.sub(r"\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}", "", top_level)
    if "," in top_level and "=" not in value:
        return False
    if len(value) >= 28:
        return True
    if _FORMULA_COMMANDS.search(value):
        return True
    if "=" in value and len(value) >= 12:
        return True
    if re.search(r"[+*/^]|\\cdot|\\times", value) and len(value) >= 8:
        return True
    return False


def _starts_sentence(sentence: str, match: re.Match) -> bool:
    """Reject mid-sentence proper nouns caught by the capitalised-term regex."""
    prefix = re.sub(r"^\s*(?:[-*•]|\d+[.)])?\s*", "", sentence[: match.start()])
    return not prefix.strip("*_` \"'«»")

_FORMULA_DELIMITERS = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$|\\\[(.+?)\\\]|\\\((.+?)\\\)", re.DOTALL)
_LATEX_COMMAND = re.compile(r"\\(?:frac|sqrt|sum|int|lim|cdot|times|pm|alpha|beta|gamma|theta|lambda|mu|sigma|pi|Delta)\b")
_MATH_SYMBOLS = re.compile(r"[=≈≠≤≥±∑∫√∞∂Δ]")

_MERGE_SYSTEM = (
    "Ты — методист, который собирает шпаргалку к экзамену по конспектам лекций. "
    "Используй только предоставленный материал: не добавляй факты, которых в нём нет. "
    "Пиши по-русски, сжато и по делу, без вводных фраз. "
    "Верни строго валидный JSON без markdown-разметки вокруг JSON и без комментариев."
)

_MERGE_TEMPLATE = """Группа: {group}
Лекций в группе: {count}

Материал (по лекциям и разделам, с таймкодами):
{digest}

Собери шпаргалку к экзамену. Ответ — JSON-объект:
{{
  "tickets": [
    {{"question": "экзаменационный вопрос", "answer": "сжатый ответ на 3-6 предложений", "lecture": 1, "time": "12:34"}}
  ],
  "definitions": [
    {{"term": "термин", "definition": "определение", "lecture": 1, "time": "03:10"}}
  ],
  "formulas": [
    {{"formula": "формула в LaTeX без $", "meaning": "что она выражает", "lecture": 1, "time": "05:00"}}
  ],
  "cheatsheet_md": "полная шпаргалка в Markdown: разделы по темам, ключевые тезисы, формулы"
}}

Требования:
- 8-20 билетов, от простых к сложным; answer должен позволять ответить без просмотра видео.
- 5-15 определений и все действительно важные формулы (если формул нет — пустой список).
- lecture — номер лекции из материала (нумерация с 1), time — таймкод ближайшего места.
- cheatsheet_md — не длиннее 6000 символов, без повторения всех билетов дословно.
"""


@dataclass
class _LectureMaterial:
    lecture: Lecture
    sections: list[Section]
    digest: str


@dataclass
class ExamSheetData:
    fingerprint: str
    lecture_ids: list[str]
    lecture_count: int
    tickets: list[dict] = field(default_factory=list)
    definitions: list[dict] = field(default_factory=list)
    formulas: list[dict] = field(default_factory=list)
    cheatsheet_md: str = ""
    mode: str = MODE_OFFLINE
    mode_used: str = MODE_OFFLINE
    model: str | None = None
    llm_used: bool = False
    generation_ms: int = 0


def _plain(value: str | None) -> str:
    text = (value or "").replace("**", "").replace("`", "")
    return normalize_space(text).strip()


def _cut_md(value: str | None, limit: int) -> str:
    """Truncate while preserving line breaks (``truncate`` collapses them)."""
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rsplit(' ', 1)[0]}…"


def _clamp(value, limit: int) -> str:
    return truncate(_plain(str(value or "")), limit)


def _section_digest(section: Section, limit: int) -> str:
    lines = [f"### {section.title} [{format_timestamp(section.start_sec)}]"]
    if section.summary:
        lines.append(_clamp(section.summary, 500))
    points = [f"- {_clamp(point, 220)}" for point in (section.key_points or [])[:6] if point]
    if points:
        lines.append("\n".join(points))
    if section.details:
        lines.append(_clamp(section.details, 700))
    return _cut_md("\n".join(lines), limit)


def _notes_signature(material: _LectureMaterial) -> str:
    lecture = material.lecture
    return json.dumps(
        {
            "title": lecture.title,
            "summary": lecture.summary,
            "questions": lecture.questions or [],
            "sections": [
                [section.idx, section.title, section.summary, section.key_points, section.details]
                for section in material.sections
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _fingerprint(materials: list[_LectureMaterial]) -> str:
    """Hash only what the sheet is built from.

    ``Lecture.updated_at`` must stay out: view counters and sharing touch the
    row through ORM updates, so ``onupdate=func.now()`` would mark a fresh
    sheet stale without a single note changing.
    """
    digest = hashlib.sha256()
    for material in materials:
        digest.update(str(material.lecture.id).encode())
        digest.update(_notes_signature(material).encode())
    return digest.hexdigest()


def _load_materials(session, group: VideoGroup) -> list[_LectureMaterial]:
    lectures = (
        session.query(Lecture)
        .filter(Lecture.group_id == group.id, Lecture.status == "ready")
        .order_by(Lecture.created_at, Lecture.id)
        .all()
    )
    if not lectures:
        return []
    sections = (
        session.query(Section)
        .filter(Section.lecture_id.in_([lecture.id for lecture in lectures]))
        .order_by(Section.lecture_id, Section.idx)
        .all()
    )
    by_lecture: dict = {}
    for section in sections:
        by_lecture.setdefault(section.lecture_id, []).append(section)
    return [
        _LectureMaterial(lecture=lecture, sections=by_lecture.get(lecture.id, []), digest="")
        for lecture in lectures
    ]


def _build_digest(materials: list[_LectureMaterial], budget: int) -> str:
    per_lecture = max(700, budget // max(1, len(materials)))
    parts = []
    for index, material in enumerate(materials, start=1):
        header = f"## Лекция {index}. {material.lecture.title}"
        body = "\n\n".join(
            _section_digest(section, per_lecture) for section in material.sections
        )
        if not body:
            body = _clamp(material.lecture.summary, per_lecture)
        material.digest = _cut_md(f"{header}\n{body}", per_lecture + 160)
        parts.append(material.digest)
    return _cut_md("\n\n".join(parts), budget)


def _lecture_ref(materials: list[_LectureMaterial], index) -> dict:
    if not materials:
        return {}
    try:
        position = int(index) - 1
    except (TypeError, ValueError):
        position = 0
    position = max(0, min(position, len(materials) - 1))
    material = materials[position]
    return {
        "lecture_id": str(material.lecture.id),
        "lecture_title": material.lecture.title,
    }


def _normalize_time(raw, material: _LectureMaterial | None) -> tuple[float, str]:
    seconds = parse_timestamp(raw)
    if seconds is not None:
        return seconds, format_timestamp(seconds)
    if material and material.sections:
        return material.sections[0].start_sec, format_timestamp(material.sections[0].start_sec)
    return 0.0, format_timestamp(0)


def _material_at(materials: list[_LectureMaterial], index) -> _LectureMaterial | None:
    try:
        position = int(index) - 1
    except (TypeError, ValueError):
        return materials[0] if materials else None
    if not materials:
        return None
    return materials[max(0, min(position, len(materials) - 1))]


def _extract_definitions(materials: list[_LectureMaterial]) -> list[dict]:
    seen: set[str] = set()
    items: list[dict] = []
    for material in materials:
        for section in material.sections:
            texts = [section.summary or "", section.details or ""]
            for raw in texts:
                for sentence in re.split(r"(?<=[.!?])\s+|\n+", raw):
                    for pattern_index, pattern in enumerate(_DEFINITION_PATTERNS):
                        match = pattern.search(sentence)
                        if not match:
                            continue
                        if pattern_index < 2 and not _starts_sentence(sentence, match):
                            continue
                        groups = match.groupdict()
                        definition = _plain(groups.get("definition"))
                        term = _plain(groups.get("term"))
                        if not term:
                            term = _clamp(section.title, 80)
                        key = re.sub(r"[^0-9a-zа-яё]+", "", term.lower())
                        if len(definition) < 12 or key in seen or not _looks_like_term(term):
                            continue
                        # «X называется Y» often yields just a name
                        # («…называется первообразной функции f(x)»), which
                        # reads backwards; real definitions carry more text.
                        if pattern_index == 1 and len(definition) < 30:
                            continue
                        seen.add(key)
                        items.append(
                            {
                                "term": truncate(term, 120),
                                "definition": truncate(definition, 400),
                                "lecture_id": str(material.lecture.id),
                                "lecture_title": material.lecture.title,
                                "start_sec": round(section.start_sec, 2),
                                "timestamp": format_timestamp(section.start_sec),
                            }
                        )
                        if len(items) >= MAX_DEFINITIONS:
                            return items
                    if len(items) >= MAX_DEFINITIONS:
                        return items
    return items


def _extract_formulas(materials: list[_LectureMaterial]) -> list[dict]:
    seen: set[str] = set()
    items: list[dict] = []
    for material in materials:
        for section in material.sections:
            for raw in (section.summary or "", section.details or ""):
                for match in _FORMULA_DELIMITERS.finditer(raw):
                    formula = next((group for group in match.groups() if group), "")
                    formula = normalize_space(formula).strip().rstrip(".,;:")
                    if formula in seen or not _is_meaningful_formula(formula):
                        continue
                    seen.add(formula)
                    items.append(
                        {
                            "formula": truncate(formula, 300),
                            "meaning": truncate(_plain(section.title), 200),
                            "lecture_id": str(material.lecture.id),
                            "lecture_title": material.lecture.title,
                            "start_sec": round(section.start_sec, 2),
                            "timestamp": format_timestamp(section.start_sec),
                        }
                    )
                for line in re.split(r"\n+", raw):
                    if _FORMULA_DELIMITERS.search(line):
                        continue
                    candidate = _plain(line).rstrip(".,;:")
                    if len(candidate) > 300 or candidate in seen:
                        continue
                    if not _is_meaningful_formula(candidate):
                        continue
                    if _LATEX_COMMAND.search(candidate) or (
                        _MATH_SYMBOLS.search(candidate) and "=" in candidate
                    ):
                        seen.add(candidate)
                        items.append(
                            {
                                "formula": truncate(candidate, 300),
                                "meaning": truncate(_plain(section.title), 200),
                                "lecture_id": str(material.lecture.id),
                                "lecture_title": material.lecture.title,
                                "start_sec": round(section.start_sec, 2),
                                "timestamp": format_timestamp(section.start_sec),
                            }
                        )
                if len(items) >= MAX_FORMULAS:
                    return items
    return items


def _fallback_tickets(materials: list[_LectureMaterial]) -> list[dict]:
    items: list[dict] = []
    for material in materials:
        sections = material.sections
        for index, question in enumerate(material.lecture.questions or []):
            section = sections[min(index, len(sections) - 1)] if sections else None
            points = [str(point) for point in (section.key_points or [])] if section else []
            answer = " ".join(points[:3]) or _plain(section.summary if section else material.lecture.summary)
            if not answer:
                continue
            items.append(
                {
                    "question": truncate(_plain(str(question)), 240),
                    "answer": truncate(answer, 700),
                    "lecture_id": str(material.lecture.id),
                    "lecture_title": material.lecture.title,
                    "start_sec": round(section.start_sec, 2) if section else 0.0,
                    "timestamp": format_timestamp(section.start_sec if section else 0),
                }
            )
            if len(items) >= MAX_TICKETS:
                return items
    return items


def _fallback_cheatsheet(materials: list[_LectureMaterial]) -> str:
    lines: list[str] = []
    for material in materials:
        lines.extend([f"## {material.lecture.title}", ""])
        if material.lecture.summary:
            lines.extend([_clamp(material.lecture.summary, 600), ""])
        for section in material.sections:
            lines.extend([f"### {section.title} · {format_timestamp(section.start_sec)}", ""])
            if section.summary:
                lines.extend([_clamp(section.summary, 400), ""])
            points = [f"- {_clamp(point, 260)}" for point in (section.key_points or [])[:4]]
            if points:
                lines.extend([*points, ""])
    return _cut_md("\n".join(lines).strip(), MAX_CHEATSHEET_CHARS)


def _clean_tickets(raw, materials: list[_LectureMaterial], fallback: list[dict]) -> list[dict]:
    if not isinstance(raw, list):
        return fallback
    items: list[dict] = []
    for entry in raw[:MAX_TICKETS]:
        if not isinstance(entry, dict):
            continue
        question = _clamp(entry.get("question"), 240)
        answer = _clamp(entry.get("answer"), 900)
        if len(question) < 8 or len(answer) < 15:
            continue
        material = _material_at(materials, entry.get("lecture"))
        ref = _lecture_ref(materials, entry.get("lecture"))
        start, stamp = _normalize_time(entry.get("time"), material)
        if material is None:
            continue
        items.append(
            {
                "question": question,
                "answer": answer,
                **ref,
                "start_sec": round(start, 2),
                "timestamp": stamp,
            }
        )
    return items or fallback


def _clean_definitions(raw, materials: list[_LectureMaterial], fallback: list[dict]) -> list[dict]:
    if not isinstance(raw, list):
        return fallback
    items: list[dict] = []
    for entry in raw[:MAX_DEFINITIONS]:
        if not isinstance(entry, dict):
            continue
        term = _clamp(entry.get("term"), 120)
        definition = _clamp(entry.get("definition"), 400)
        if len(term) < 2 or len(definition) < 12:
            continue
        material = _material_at(materials, entry.get("lecture"))
        ref = _lecture_ref(materials, entry.get("lecture"))
        start, stamp = _normalize_time(entry.get("time"), material)
        items.append(
            {
                "term": term,
                "definition": definition,
                **ref,
                "start_sec": round(start, 2),
                "timestamp": stamp,
            }
        )
    return items or fallback


def _clean_formulas(raw, materials: list[_LectureMaterial], fallback: list[dict]) -> list[dict]:
    if not isinstance(raw, list):
        return fallback
    items: list[dict] = []
    for entry in raw[:MAX_FORMULAS]:
        if not isinstance(entry, dict):
            continue
        formula = _clamp(entry.get("formula"), 300).strip("$").strip()
        if len(formula) < 2:
            continue
        material = _material_at(materials, entry.get("lecture"))
        ref = _lecture_ref(materials, entry.get("lecture"))
        start, stamp = _normalize_time(entry.get("time"), material)
        items.append(
            {
                "formula": formula,
                "meaning": _clamp(entry.get("meaning"), 200),
                **ref,
                "start_sec": round(start, 2),
                "timestamp": stamp,
            }
        )
    return items or fallback


def _merge_with_llm(
    client,
    group: VideoGroup,
    materials: list[_LectureMaterial],
    digest: str,
    fallback: tuple[list[dict], list[dict], list[dict], str],
) -> tuple[list[dict], list[dict], list[dict], str, str | None]:
    fallback_tickets, fallback_definitions, fallback_formulas, fallback_md = fallback
    prompt = _MERGE_TEMPLATE.format(group=group.name, count=len(materials), digest=digest)
    try:
        data = client.chat_json(
            [
                {"role": "system", "content": _MERGE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=4096,
            temperature=0.2,
        )
    except LlmUnavailable as exc:
        log.warning("exam sheet: llm unavailable (%s), deterministic merge", exc)
        return fallback_tickets, fallback_definitions, fallback_formulas, fallback_md, None, False
    except Exception:  # pragma: no cover - malformed answer must not break the page
        log.exception("exam sheet: merge call failed")
        return fallback_tickets, fallback_definitions, fallback_formulas, fallback_md, None, False
    if not isinstance(data, dict):
        return fallback_tickets, fallback_definitions, fallback_formulas, fallback_md, None, False
    tickets = _clean_tickets(data.get("tickets"), materials, fallback_tickets)
    definitions = _clean_definitions(data.get("definitions"), materials, fallback_definitions)
    formulas = _clean_formulas(data.get("formulas"), materials, fallback_formulas)
    cheatsheet = data.get("cheatsheet_md")
    cheatsheet_md = (
        _cut_md(cheatsheet, MAX_CHEATSHEET_CHARS)
        if isinstance(cheatsheet, str) and len(cheatsheet.strip()) > 80
        else fallback_md
    )
    model = getattr(client, "model", None)
    return tickets, definitions, formulas, cheatsheet_md, model, True


def build_exam_sheet(
    session,

    group: VideoGroup,
    *,
    mode: str | None = None,
) -> ExamSheetData:
    started = time.perf_counter()
    requested = normalize_mode(mode or group_mode_hint(session, group))
    materials = _load_materials(session, group)
    if not materials:
        raise ValueError("no ready lectures in group")

    budget = 24_000 if requested == "api" else 9_000
    digest = _build_digest(materials, budget)
    fingerprint = _fingerprint(materials)

    definitions = _extract_definitions(materials)
    formulas = _extract_formulas(materials)
    tickets = _fallback_tickets(materials)
    cheatsheet_md = _fallback_cheatsheet(materials)

    mode_used, client = resolve_client(requested)
    model = None
    llm_used = False
    if client is not None and digest.strip():
        (
            tickets,
            definitions,
            formulas,
            cheatsheet_md,
            model,
            llm_used,
        ) = _merge_with_llm(
            client,
            group,
            materials,
            digest,
            (tickets, definitions, formulas, cheatsheet_md),
        )
        if not llm_used:
            mode_used = MODE_OFFLINE
    else:
        mode_used = MODE_OFFLINE

    elapsed = int((time.perf_counter() - started) * 1000)
    return ExamSheetData(
        fingerprint=fingerprint,
        lecture_ids=[str(material.lecture.id) for material in materials],
        lecture_count=len(materials),
        tickets=tickets,
        definitions=definitions,
        formulas=formulas,
        cheatsheet_md=cheatsheet_md,
        mode=requested,
        mode_used=mode_used,
        model=model,
        llm_used=llm_used,
        generation_ms=elapsed,
    )


def group_mode_hint(session, group: VideoGroup) -> str:
    """Prefer the notes mode already used in the group, so the sheet matches."""
    row = (
        session.query(Lecture.llm_mode_used)
        .filter(Lecture.group_id == group.id, Lecture.status == "ready")
        .order_by(Lecture.created_at.desc())
        .first()
    )
    value = row[0] if row else ""
    try:
        return normalize_mode(value or "api")
    except ValueError:
        return "api"


def current_fingerprint(session, group: VideoGroup) -> tuple[str, int]:
    materials = _load_materials(session, group)
    return _fingerprint(materials), len(materials)


def save_exam_sheet(session, group: VideoGroup, data: ExamSheetData) -> ExamSheet:
    sheet = session.query(ExamSheet).filter(ExamSheet.group_id == group.id).first()
    if sheet is None:
        sheet = ExamSheet(group_id=group.id, owner_id=group.owner_id)
        session.add(sheet)
    sheet.fingerprint = data.fingerprint
    sheet.lecture_ids = data.lecture_ids
    sheet.lecture_count = data.lecture_count
    sheet.tickets = data.tickets
    sheet.definitions = data.definitions
    sheet.formulas = data.formulas
    sheet.cheatsheet_md = data.cheatsheet_md
    sheet.llm_mode = data.mode
    sheet.llm_mode_used = data.mode_used
    sheet.llm_model = data.model
    sheet.generation_ms = data.generation_ms
    session.commit()
    session.refresh(sheet)
    return sheet


def sheet_payload(sheet: ExamSheet | None, *, fingerprint: str, lecture_count: int) -> dict:
    if sheet is None:
        return {
            "status": "missing",
            "stale": False,
            "lecture_count": lecture_count,
            "tickets": [],
            "definitions": [],
            "formulas": [],
            "cheatsheet_md": "",
        }
    payload = {
        "status": "ready",
        "stale": sheet.fingerprint != fingerprint,
        "lecture_count": sheet.lecture_count,
        "current_lecture_count": lecture_count,
        "tickets": list(sheet.tickets or []),
        "definitions": list(sheet.definitions or []),
        "formulas": list(sheet.formulas or []),
        "cheatsheet_md": sheet.cheatsheet_md or "",
        "llm_mode": sheet.llm_mode,
        "llm_mode_used": sheet.llm_mode_used,
        "llm_model": sheet.llm_model,
        "generation_ms": sheet.generation_ms,
        "generated_at": sheet.updated_at.isoformat() if sheet.updated_at else None,
    }
    return payload
