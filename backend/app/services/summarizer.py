"""Lecture notes: abstract, outline with timestamps, keywords, details.

Three strategies, one contract (``StudyNotes``):

* **api** — DeepSeek Web through the local FreeDeepseekAPI proxy.  A multi-pass
  map → outline → per-section details → overview pipeline produces a much
  larger, better structured conspectus than a single local call.  Every call
  is rate-limited and isolated by :mod:`app.services.llm_api`.
* **local** — the llama.cpp model on this machine, one reduce call that fits
  its small context window.
* **offline fallback** — deterministic sentence scoring + time buckets, used
  only when neither model works (marked as ``offline`` in the output).

All three return validated data: timestamps are ordered and bounded, empty
sections are dropped, and a failed model call degrades to the next strategy
instead of showing a dead end.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from ..config import Config
from ..utils.text import (
    capitalize_first,
    content_tokens,
    normalize_space,
    split_sentences,
    truncate,
)
from ..utils.text import (
    keywords as top_keywords,
)
from ..utils.timefmt import clock, format_timestamp, parse_timestamp
from .asr import Segment
from .llm import LlmUnavailable, llm
from .llm_base import OpenAiCompatClient
from .llm_modes import (
    MODE_API,
    MODE_LOCAL,
    MODE_OFFLINE,
    default_mode,
    normalize_mode,
    resolve_client,
)

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str], None]

_TITLE_FIXES = (
    (r"\bплюс[\s-]*плюс\w*\b", "C++"),
    (r"\bплюсах\b", "C++"),
    (r"\bпайтон\w*\b", "Python"),
    (r"\bпитон\w*\b", "Python"),
    (r"\bджава[\s-]*скрипт\w*\b", "JavaScript"),
    (r"\bси[\s-]*шарп\w*\b", "C#"),
    (r"\bджава\b", "Java"),
)


def _fix_tech_names(title: str) -> str:
    """ASR writes «плюс плюс» instead of C++ — restore the usual spelling."""
    for pattern, replacement in _TITLE_FIXES:
        title = re.sub(pattern, replacement, title, flags=re.IGNORECASE)
    return normalize_space(title)


_SYSTEM = (
    "Ты — опытный методист и редактор учебных конспектов. Ты работаешь только с "
    "предоставленной расшифровкой лекции, не выдумываешь факты и не добавляешь "
    "того, чего не было в записи. Отвечаешь на русском языке. "
    "Возвращаешь строго валидный JSON без markdown-разметки и комментариев."
)

_API_SYSTEM = (
    "Ты — опытный методист и редактор учебных конспектов. Ты работаешь только с "
    "предоставленной расшифровкой лекции, не выдумываешь факты и не добавляешь "
    "того, чего не было в записи. Отвечаешь на русском языке. "
    "Пиши подробно, развёрнуто и по делу: конспект должен быть пригоден для "
    "подготовки к экзамену без просмотра видео. "
    "Возвращаешь строго валидный JSON без markdown-разметки вокруг JSON и без "
    "комментариев."
)


@dataclass
class SectionDraft:
    title: str
    start_sec: float
    end_sec: float
    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    details: str = ""

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "start_sec": round(self.start_sec, 2),
            "end_sec": round(self.end_sec, 2),
            "summary": self.summary,
            "key_points": self.key_points,
            "details": self.details,
            "timestamp": format_timestamp(self.start_sec),
        }


@dataclass
class StudyNotes:
    summary: str
    sections: list[SectionDraft]
    keywords: list[str]
    llm_used: bool
    mode: str = MODE_OFFLINE
    model: str | None = None
    title: str | None = None
    category: str | None = None
    subcategory: str | None = None
    questions: list[str] = field(default_factory=list)


class Summarizer:
    # -- public API ----------------------------------------------------
    def build(
        self,
        *,
        title: str,
        segments: Sequence[Segment],
        duration_sec: float,
        mode: str | None = None,
        on_progress: ProgressCb | None = None,
    ) -> StudyNotes:
        if not segments:
            raise ValueError("no segments to summarise")

        requested = self._safe_mode(mode)
        fallback = self._extractive(title=title, segments=segments, duration=duration_sec)

        resolved, client = resolve_client(requested)
        if client is None:
            log.warning("summariser: %s unavailable, extractive notes", requested)
            return fallback

        log.info(
            "summariser: requested=%s resolved=%s model=%s",
            requested,
            resolved,
            getattr(client, "model", "?"),
        )
        try:
            if resolved == MODE_API:
                notes = self._api_notes(
                    client=client,
                    title=title,
                    segments=segments,
                    duration_sec=duration_sec,
                    on_progress=on_progress,
                )
            else:
                notes = self._local_notes(
                    client=client,
                    title=title,
                    segments=segments,
                    duration_sec=duration_sec,
                )
            if notes and notes.sections:
                log.info(
                    "summariser: %s notes ready (%d sections, %d words in abstract)",
                    notes.mode,
                    len(notes.sections),
                    len(notes.summary.split()),
                )
                return notes
        except LlmUnavailable as exc:
            log.warning("summariser: %s model failed (%s)", resolved, exc)
        except Exception:
            log.exception("summariser: unexpected failure (%s)", resolved)

        # The API can fail mid-run (account cooldown).  The local model is the
        # next best thing, then extractive notes; never fail the lecture.
        if resolved == MODE_API:
            try:
                if llm.enabled and llm.available:
                    log.info("summariser: falling back to the local model")
                    notes = self._local_notes(
                        client=llm,
                        title=title,
                        segments=segments,
                        duration_sec=duration_sec,
                    )
                    if notes and notes.sections:
                        return notes
            except Exception:
                log.exception("summariser: local fallback failed")
        return fallback

    # -- API path: map → outline → details → overview --------------------
    def _api_notes(
        self,
        *,
        client: OpenAiCompatClient,
        title: str,
        segments: Sequence[Segment],
        duration_sec: float,
        on_progress: ProgressCb | None = None,
    ) -> StudyNotes | None:
        target = self._target_sections(duration_sec)

        self._emit(on_progress, 0.02, "notes_map")
        context = self._api_context(client, segments, on_progress=on_progress)
        if not context:
            return None

        self._emit(on_progress, 0.26, "notes_outline")
        outline = self._api_outline(
            client,
            context=context,
            title=title,
            duration_sec=duration_sec,
            target=target,
        )
        if not outline or len(outline["sections"]) < 3:
            log.warning(
                "summariser: API outline is too small (%d sections)",
                len(outline["sections"]) if outline else 0,
            )
            return None

        self._emit(on_progress, 0.46, "notes_details")
        drafts = self._api_details(
            client,
            outline=outline["sections"],
            segments=segments,
            duration_sec=duration_sec,
            on_progress=on_progress,
        )
        if not drafts:
            return None

        # A transient account cooldown may affect one detail batch.  The local
        # fallback above keeps the lecture usable, but API mode should not
        # silently return a paper-thin section when the proxy recovered.
        detailed_count = sum(1 for draft in drafts if draft.details and len(draft.key_points) >= 3)
        if detailed_count < max(3, math.ceil(len(drafts) * 0.5)):
            log.warning(
                "summariser: API details quality low (%d/%d), retaining grounded fallbacks",
                detailed_count,
                len(drafts),
            )

        self._emit(on_progress, 0.9, "notes_summary")
        overview = self._api_overview(
            client,
            outline=outline,
            drafts=drafts,
            duration_sec=duration_sec,
        )
        if overview is None:
            overview = self._fallback_overview(outline, drafts, segments)

        data = {
            "title": overview.get("title") or outline.get("title"),
            "category": overview.get("category") or outline.get("category"),
            "subcategory": overview.get("subcategory") or outline.get("subcategory"),
            "summary": overview.get("summary") or "",
            "keywords": overview.get("keywords") or [],
            "questions": overview.get("questions") or [],
            "sections": [draft.as_dict() for draft in drafts],
        }
        notes = self._validate(
            data, duration_sec, mode=MODE_API, model=getattr(client, "model", None)
        )
        self._emit(on_progress, 1.0, "notes_summary")
        return notes

    # -- API: context / map phase --------------------------------------
    def _api_context(
        self,
        client: OpenAiCompatClient,
        segments: Sequence[Segment],
        *,
        on_progress: ProgressCb | None = None,
    ) -> str:
        budget = Config.API_LLM_MAX_INPUT_CHARS
        digest = self._digest(segments, max_chars=budget + 1)
        if len(digest) <= budget:
            return digest

        total_chars = sum(len(segment.text) + 12 for segment in segments)
        max_windows = max(2, Config.API_LLM_MAX_MAP_WINDOWS)
        window_chars = max(
            Config.API_LLM_MAP_WINDOW_CHARS,
            math.ceil(total_chars / max_windows) + 500,
        )
        windows = self._windows(segments, max_chars=window_chars)
        if len(windows) > max_windows:  # pragma: no cover - very long lectures
            windows = self._merge_windows(windows, max_windows)

        log.info(
            "summariser: long lecture, mapping %d window(s) (%d chars)",
            len(windows),
            total_chars,
        )
        chunks: list[str] = []
        for index, window in enumerate(windows, start=1):
            window_digest = self._digest(window, max_chars=window_chars + 1000)
            payload = (
                f"Часть {index} из {len(windows)}. Законспектируй фрагмент лекции.\n"
                "Верни JSON ровно такой структуры:\n"
                '{"notes": [{"start_sec": 123, "thesis": "конкретный тезис"}], '
                '"terms": ["термин"]}\n'
                "Требования: 8-12 содержательных тезисов, каждый с таймкодом начала "
                "мысли; 5-10 терминов; без общих слов и без выдуманных фактов.\n\n"
                f"РАСШИФРОВКА:\n{window_digest}"
            )
            try:
                data = client.chat_json(
                    [
                        {"role": "system", "content": _API_SYSTEM},
                        {"role": "user", "content": payload},
                    ],
                    max_tokens=1800,
                    temperature=0.2,
                )
                text = self._format_map_notes(data)
            except LlmUnavailable as exc:
                log.warning("summariser: map window %d failed (%s)", index, exc)
                text = ""
            except Exception:
                log.exception("summariser: map window %d crashed", index)
                text = ""
            if not text:
                text = self._window_fallback(window)
            chunks.append(text)
            self._emit(on_progress, 0.04 + 0.2 * (index / len(windows)), "notes_map")

        combined = "Тезисы по фрагментам лекции (с таймкодами):\n" + "\n".join(chunks)
        return self._clip(combined, budget)

    @staticmethod
    def _format_map_notes(data: dict | list) -> str:
        if not isinstance(data, dict):
            return ""
        notes = data.get("notes") or []
        lines: list[str] = []
        for item in notes:
            if not isinstance(item, dict):
                continue
            thesis = normalize_space(str(item.get("thesis") or item.get("text") or ""))
            if not thesis:
                continue
            start = parse_timestamp(item.get("start_sec")) or 0.0
            lines.append(f"[{clock(start)}] {truncate(thesis, 400)}")
        terms = [
            normalize_space(str(term))
            for term in (data.get("terms") or [])
            if str(term).strip()
        ][:10]
        if terms:
            lines.append("Термины: " + ", ".join(terms))
        return "\n".join(lines)

    @staticmethod
    def _window_fallback(window: Sequence[Segment]) -> str:
        step = max(1, len(window) // 10)
        picks = list(window)[::step][:10] or list(window)[:1]
        return "\n".join(
            f"[{clock(segment.start_sec)}] {truncate(segment.text, 360)}"
            for segment in picks
        )

    # -- API: outline ---------------------------------------------------
    def _api_outline(
        self,
        client: OpenAiCompatClient,
        *,
        context: str,
        title: str,
        duration_sec: float,
        target: int,
    ) -> dict | None:
        header = (
            f"Лекция: «{title}»."
            if title
            else "Рабочее название не задано — придумай его сам."
        )
        minimum = max(4, min(target - 2, Config.API_LLM_NOTES_MIN_SECTIONS))
        maximum = max(minimum + 2, min(target + 4, Config.API_LLM_NOTES_MAX_SECTIONS))
        payload = (
            f"{header} Длительность: {format_timestamp(duration_sec)}.\n"
            "Ниже расшифровка с таймкодами в формате [мм:сс].\n\n"
            f"РАСШИФРОВКА:\n{context}\n\n"
            "Составь план учебного конспекта. Верни JSON ровно такой структуры:\n"
            '{\n'
            '  "title": "название лекции (3-7 слов, без кавычек и точки)",\n'
            '  "category": "широкая область содержания (1-3 слова)",\n'
            '  "subcategory": "конкретная тема внутри области (1-5 слов)",\n'
            '  "sections": [\n'
            '    {"title": "короткое название раздела (2-7 слов)", '
            '"focus": "о чём раздел, 1-2 предложения", '
            '"start_sec": 0, "end_sec": 120}\n'
            "  ]\n"
            "}\n\n"
            "Требования:\n"
            f"1. {minimum}-{maximum} разделов, по порядку, без разрывов и перекрытий.\n"
            "2. start_sec и end_sec — целые секунды из таймкодов; первый раздел "
            "начинается с 0, последний заканчивается в конце лекции.\n"
            "3. Разделы должны соответствовать реальным смысловым блокам, а не "
            "равным интервалам.\n"
            "4. title — конкретная тема: «Прямоугольный параллелепипед и тела "
            "вращения», а не «Лекция по геометрии».\n"
            "5. Не придумывай факты и разделы, которых нет в расшифровке.\n"
            "6. Только JSON, без пояснений."
        )
        try:
            data = client.chat_json(
                [
                    {"role": "system", "content": _API_SYSTEM},
                    {"role": "user", "content": payload},
                ],
                max_tokens=2600,
                temperature=0.2,
            )
        except LlmUnavailable as exc:
            log.warning("summariser: API outline failed (%s)", exc)
            return None

        outline = self._normalize_outline(data, duration_sec)
        if outline is None or len(outline["sections"]) >= min(4, minimum):
            return outline

        log.info(
            "summariser: only %d sections in outline, retrying",
            len(outline["sections"]),
        )
        try:
            retry = client.chat_json(
                [
                    {"role": "system", "content": _API_SYSTEM},
                    {"role": "user", "content": payload},
                    {
                        "role": "user",
                        "content": (
                            f"Разделов слишком мало. Верни {minimum}-{maximum} разделов "
                            "с таймкодами, как требуется в задании. Только JSON."
                        ),
                    },
                ],
                max_tokens=2600,
                temperature=0.1,
            )
        except LlmUnavailable:
            return outline
        retried = self._normalize_outline(retry, duration_sec)
        if retried and len(retried["sections"]) >= len(outline["sections"]):
            return retried
        return outline

    def _normalize_outline(self, data: dict | list, duration: float) -> dict | None:
        if not isinstance(data, dict):
            return None
        raw_sections = data.get("sections") or []
        sections: list[dict] = []
        for item in raw_sections:
            if not isinstance(item, dict):
                continue
            title = normalize_space(str(item.get("title") or "")).strip(" .")
            if not title:
                continue
            start = parse_timestamp(item.get("start_sec")) or 0.0
            end = parse_timestamp(item.get("end_sec")) or 0.0
            if end <= start:
                end = start + 30.0
            start = max(0.0, min(start, duration or start))
            end = max(start + 5.0, min(end, duration or end))
            sections.append(
                {
                    "title": truncate(title, 90),
                    "focus": normalize_space(str(item.get("focus") or "")),
                    "start_sec": start,
                    "end_sec": end,
                }
            )
        if len(sections) < 2:
            return None
        sections.sort(key=lambda item: item["start_sec"])
        sections[0]["start_sec"] = 0.0
        for left, right in zip(sections, sections[1:]):
            left["end_sec"] = max(left["start_sec"] + 5.0, min(left["end_sec"], right["start_sec"]))
            right["start_sec"] = max(right["start_sec"], left["end_sec"])
        sections[-1]["end_sec"] = max(
            sections[-1]["start_sec"] + 10.0, duration or sections[-1]["end_sec"]
        )
        return {
            "title": normalize_space(str(data.get("title") or "")).strip(' "«»\'.'),
            "category": normalize_space(str(data.get("category") or "")).strip(' "«»\'.'),
            "subcategory": normalize_space(str(data.get("subcategory") or "")).strip(
                ' "«»\'.'
            ),
            "sections": sections,
        }

    # -- API: per-section details --------------------------------------
    def _api_details(
        self,
        client: OpenAiCompatClient,
        *,
        outline: list[dict],
        segments: Sequence[Segment],
        duration_sec: float,
        on_progress: ProgressCb | None = None,
    ) -> list[SectionDraft] | None:
        slices = [self._section_slice(segments, item) for item in outline]
        batches = self._detail_batches(outline, slices)
        results: dict[int, dict] = {}
        for done, batch in enumerate(batches, start=1):
            prompt = self._details_prompt(outline, slices, batch)
            try:
                data = client.chat_json(
                    [
                        {"role": "system", "content": _API_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=8000,
                    temperature=0.3,
                )
                for item in (data.get("sections") if isinstance(data, dict) else []) or []:
                    if not isinstance(item, dict):
                        continue
                    try:
                        index = int(item.get("index"))
                    except (TypeError, ValueError):
                        continue
                    if index not in batch:
                        continue
                    results[index] = self._clean_section_payload(item)
            except LlmUnavailable as exc:
                log.warning("summariser: details batch %d failed (%s)", done, exc)
            except Exception:
                log.exception("summariser: details batch %d crashed", done)
            self._emit(
                on_progress,
                0.48 + 0.4 * (done / max(1, len(batches))),
                "notes_details",
            )

        drafts: list[SectionDraft] = []
        for index, item in enumerate(outline):
            payload = results.get(index)
            if not payload or not payload.get("summary"):
                payload = self._section_fallback(item, slices[index])
            drafts.append(
                SectionDraft(
                    title=item["title"],
                    start_sec=item["start_sec"],
                    end_sec=item["end_sec"],
                    summary=payload.get("summary") or "",
                    key_points=payload.get("key_points") or [],
                    details=payload.get("details") or "",
                )
            )
        return drafts or None

    @staticmethod
    def _section_slice(segments: Sequence[Segment], section: dict) -> list[Segment]:
        start, end = section["start_sec"], section["end_sec"]
        selected = [
            segment
            for segment in segments
            if segment.end_sec >= start - 1.5 and segment.start_sec <= end + 1.5
        ]
        if selected:
            return selected
        # A silent stretch: take the nearest two segments so the section still
        # has grounded text for its summary.
        ordered = sorted(segments, key=lambda segment: abs(segment.start_sec - start))
        return sorted(ordered[:2], key=lambda segment: segment.start_sec)

    @staticmethod
    def _detail_batches(
        outline: list[dict], slices: list[list[Segment]]
    ) -> list[list[int]]:
        limit = max(2000, Config.API_LLM_DETAILS_BATCH_CHARS)
        batches: list[list[int]] = []
        current: list[int] = []
        current_chars = 0
        for index, window in enumerate(slices):
            size = sum(len(segment.text) + 16 for segment in window)
            if current and (current_chars + size > limit or len(current) >= 3):
                batches.append(current)
                current = []
                current_chars = 0
            current.append(index)
            current_chars += size
        if current:
            batches.append(current)
        return batches

    def _details_prompt(
        self, outline: list[dict], slices: list[list[Segment]], batch: list[int]
    ) -> str:
        blocks: list[str] = []
        for index in batch:
            section = outline[index]
            digest = self._digest(slices[index], max_chars=Config.API_LLM_DETAILS_BATCH_CHARS)
            blocks.append(
                f'РАЗДЕЛ {index}: «{section["title"]}» '
                f'({format_timestamp(section["start_sec"])}–'
                f'{format_timestamp(section["end_sec"])})\n'
                f"{digest}"
            )
        return (
            "Ниже фрагменты расшифровки по разделам лекции. Для каждого раздела "
            "составь подробный учебный конспект.\n"
            "Верни JSON ровно такой структуры:\n"
            '{"sections": [{"index": 0, "summary": "подробное описание раздела на '
            '60-110 слов, 4-6 предложений", "key_points": ["тезис", "тезис"], '
            '"details": "markdown-конспект раздела: 2-4 абзаца, формулы, '
            'определения и примеры из лекции"}]}\n\n'
            "Требования:\n"
            "1. index — номер раздела из заголовка РАЗДЕЛ N, без изменений.\n"
            "2. summary — связный пересказ именно этого раздела, не общие слова.\n"
            "3. key_points — 4-6 конкретных тезисов из расшифровки.\n"
            "4. details — развёрнутый конспект в markdown: абзацы, списки, формулы "
            "в LaTeX. Только то, что прозвучало в лекции.\n"
            "5. Не придумывай факты. Если фрагмент неразборчив — опиши только "
            "понятное.\n"
            "6. Только JSON, без пояснений.\n\n" + "\n\n".join(blocks)
        )

    def _clean_section_payload(self, item: dict) -> dict:
        summary = normalize_space(str(item.get("summary") or ""))
        key_points = [
            truncate(normalize_space(str(point)), 300)
            for point in (item.get("key_points") or [])
            if normalize_space(str(point))
        ][:6]
        details = self._clean_details(str(item.get("details") or ""))
        return {"summary": summary, "key_points": key_points, "details": details}

    @staticmethod
    def _clean_details(raw: str) -> str:
        text = (raw or "").strip()
        if not text:
            return ""
        text = re.sub(r"^```(?:markdown|md)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return truncate(text, 6000) if len(text) > 6000 else text

    def _section_fallback(self, section: dict, window: Sequence[Segment]) -> dict:
        sentences: list[tuple[float, str]] = []
        for segment in window:
            for sentence in split_sentences(segment.text) or [segment.text]:
                clean = normalize_space(sentence)
                if len(clean) > 20:
                    sentences.append((segment.start_sec, clean))
        if not sentences:
            return {"summary": "", "key_points": [], "details": ""}
        step = max(1, len(sentences) // 6)
        picks = sentences[::step][:6]
        summary = truncate(" ".join(text for _, text in picks[:4]), 900)
        key_points = [truncate(text, 240) for _, text in picks[:5]]
        details = "\n\n".join(text for _, text in picks)
        return {"summary": summary, "key_points": key_points, "details": details}

    # -- API: lecture overview -----------------------------------------
    def _api_overview(
        self,
        client: OpenAiCompatClient,
        *,
        outline: dict,
        drafts: list[SectionDraft],
        duration_sec: float,
    ) -> dict | None:
        lines = [
            f'{index}: «{draft.title}» ({format_timestamp(draft.start_sec)}–'
            f'{format_timestamp(draft.end_sec)}). {draft.summary}'
            for index, draft in enumerate(drafts, start=1)
        ]
        payload = (
            f"Лекция «{outline.get('title') or 'без названия'}», длительность "
            f"{format_timestamp(duration_sec)}.\n"
            "Ниже готовый план с описаниями разделов.\n\n" + "\n".join(lines) + "\n\n"
            "Составь обзор всей лекции. Верни JSON ровно такой структуры:\n"
            '{\n'
            '  "title": "название лекции (3-7 слов)",\n'
            '  "category": "широкая область (1-3 слова)",\n'
            '  "subcategory": "конкретная тема (1-5 слов)",\n'
            '  "summary": "связный подробный обзор на 180-300 слов, 10-16 предложений",\n'
            '  "keywords": ["термин", "термин"],\n'
            '  "questions": ["вопрос для самопроверки", "вопрос"]\n'
            "}\n\n"
            "Требования:\n"
            "1. summary — цельный текст: о чём лекция, какие темы и формулы "
            "разобраны, чем она полезна. Не перечисляй разделы по очереди и не "
            "повторяй одни и те же формулировки.\n"
            "2. keywords — 14-20 ключевых терминов в именительном падеже.\n"
            "3. questions — 5-8 вопросов для самопроверки по содержанию лекции.\n"
            "4. title, category и subcategory — конкретные, без слова «лекция».\n"
            "5. Только JSON, без пояснений."
        )
        try:
            data = client.chat_json(
                [
                    {"role": "system", "content": _API_SYSTEM},
                    {"role": "user", "content": payload},
                ],
                max_tokens=3000,
                temperature=0.35,
            )
        except LlmUnavailable as exc:
            log.warning("summariser: API overview failed (%s)", exc)
            return None
        if not isinstance(data, dict):
            return None
        summary = normalize_space(str(data.get("summary") or ""))
        if len(summary.split()) < 80:
            log.warning("summariser: API overview is too short (%d words)", len(summary.split()))
            return None
        keywords = [
            normalize_space(str(word)).lower()
            for word in (data.get("keywords") or [])
            if normalize_space(str(word))
        ][:20]
        questions = self._normalize_questions(data.get("questions"))
        return {
            "title": normalize_space(str(data.get("title") or "")),
            "category": normalize_space(str(data.get("category") or "")),
            "subcategory": normalize_space(str(data.get("subcategory") or "")),
            "summary": summary,
            "keywords": keywords,
            "questions": questions,
        }

    def _fallback_overview(
        self,
        outline: dict,
        drafts: list[SectionDraft],
        segments: Sequence[Segment],
    ) -> dict:
        summary = " ".join(draft.summary.strip() for draft in drafts if draft.summary)
        if len(summary.split()) < 120:
            summary += " " + " ".join(
                point for draft in drafts[:4] for point in draft.key_points[:2]
            )
        keyword_list = top_keywords([segment.text for segment in segments], 18)
        for draft in drafts:
            keyword_list.extend(top_keywords([draft.title], 1))
        seen: set[str] = set()
        keywords = [word for word in keyword_list if not (word in seen or seen.add(word))][:18]
        questions = [f"Что такое {word}?" for word in keywords[:6]]
        return {
            "title": outline.get("title") or "",
            "category": outline.get("category") or "",
            "subcategory": outline.get("subcategory") or "",
            "summary": summary,
            "keywords": keywords,
            "questions": questions,
        }

    # -- local model path ----------------------------------------------
    def _local_notes(
        self,
        *,
        client: OpenAiCompatClient,
        title: str,
        segments: Sequence[Segment],
        duration_sec: float,
    ) -> StudyNotes | None:
        digest = self._digest(segments, max_chars=Config.SUMMARY_MAX_INPUT_CHARS)
        if not digest:
            return None

        if len(digest) <= Config.SUMMARY_MAX_INPUT_CHARS:
            payload = self._reduce_payload(title, digest, duration_sec)
        else:  # pragma: no cover - only for very long lectures
            notes = self._map_notes(segments)
            payload = self._reduce_payload(
                title, json.dumps(notes, ensure_ascii=False), duration_sec
            )

        data = client.chat_json(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": payload},
            ],
            max_tokens=Config.LLM_MAX_TOKENS,
            temperature=0.2,
        )
        if not isinstance(data, dict):
            return None
        notes = self._validate(
            data, duration_sec, mode=MODE_LOCAL, model=getattr(client, "model", None)
        )
        if notes is not None and len(notes.sections) < 3:
            # The model sometimes returns 2 broad chapters; ask once for a proper outline.
            log.info("summariser: only %d sections, retrying", len(notes.sections))
            try:
                retry = client.chat_json(
                    [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": payload},
                        {
                            "role": "user",
                            "content": "Разделов слишком мало. Верни 3-8 разделов "
                            "с таймкодами, как требуется в задании. Только JSON.",
                        },
                    ],
                    max_tokens=Config.LLM_MAX_TOKENS,
                    temperature=0.1,
                )
                if isinstance(retry, dict):
                    retried = self._validate(
                        retry,
                        duration_sec,
                        mode=MODE_LOCAL,
                        model=getattr(client, "model", None),
                    )
                    if retried is not None and len(retried.sections) >= len(notes.sections):
                        notes = retried
            except LlmUnavailable:
                pass
        return notes

    def _reduce_payload(self, title: str, transcript: str, duration: float) -> str:
        header = f"Лекция: «{title}»." if title else "Рабочее название не задано — придумай его сам."
        return f"""{header} Длительность: {format_timestamp(duration)}.
Ниже расшифровка с таймкодами в формате [мм:сс].

{transcript}

Составь учебный конспект. Верни JSON ровно такой структуры:
{{
  "title": "название лекции (3-7 слов, без кавычек и точки)",
  "category": "широкая область содержания (1-3 слова)",
  "subcategory": "конкретная тема внутри области (1-5 слов)",
  "summary": "связный обзор лекции на 70-110 слов, 3-4 предложения",
  "sections": [
    {{
      "title": "короткое название раздела (2-7 слов)",
      "summary": "1-2 предложения о чём этот раздел",
      "start_sec": 0,
      "end_sec": 120,
      "key_points": ["тезис", "тезис"]
    }}
  ],
  "keywords": ["термин", "термин"]
}}

Требования:
1. 3-8 разделов, они идут по порядку и покрывают всю лекцию без разрывов.
2. start_sec и end_sec — целые секунды из таймкодов; первый раздел начинается с 0.
3. В key_points — 2-4 конкретных тезиса из лекции, не общие слова.
4. summary — это цельный обзор: о чём лекция, какие темы разобраны, кому полезна.
   Не перечисляй разделы по очереди и не повторяй одни и те же формулировки.
5. keywords — 8-12 ключевых терминов в именительном падеже.
6. title — конкретное название темы: «Прямоугольный параллелепипед и тела вращения»,
   а не «Лекция по геометрии». Без кавычек, без слова «лекция», без точки в конце.
   Не повторяй рабочее название и не пиши «без названия».
7. Не придумывай факты, которых нет в расшифровке. Если фрагмент неразборчив — пропусти его.
8. Только JSON, без пояснений."""

    def _map_notes(self, segments: Sequence[Segment]) -> list[dict]:
        """Map phase for lectures longer than the local context window."""
        windows = self._windows(segments, max_chars=6000)
        notes: list[dict] = []
        for index, window in enumerate(windows, start=1):
            digest = self._digest(window, max_chars=6000)
            try:
                data = llm.chat_json(
                    [
                        {"role": "system", "content": _SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                f"Часть {index} из {len(windows)}. Кратко законспектируй "
                                "фрагмент лекции. Верни JSON: "
                                '{"notes": [{"time_sec": 123, "thesis": "тезис"}]} — '
                                "4-7 тезисов, каждый с таймкодом начала мысли.\n\n"
                                f"{digest}"
                            ),
                        },
                    ],
                    max_tokens=700,
                    temperature=0.1,
                )
            except LlmUnavailable:
                continue
            if isinstance(data, dict):
                notes.extend(data.get("notes") or [])
        return notes

    # -- validation -----------------------------------------------------
    def _validate(
        self,
        data: dict,
        duration: float,
        *,
        mode: str = MODE_LOCAL,
        model: str | None = None,
    ) -> StudyNotes | None:
        detailed = mode == MODE_API
        summary = normalize_space(str(data.get("summary") or ""))
        raw_sections = data.get("sections") or []
        sections: list[SectionDraft] = []
        for item in raw_sections:
            if not isinstance(item, dict):
                continue
            title = normalize_space(str(item.get("title") or "")).strip(" .")
            if not title:
                continue
            start = parse_timestamp(item.get("start_sec")) or 0.0
            end = parse_timestamp(item.get("end_sec")) or 0.0
            if end <= start:
                end = start + 30.0
            key_points = [
                normalize_space(str(point))
                for point in (item.get("key_points") or [])
                if str(point).strip()
            ][: 6 if detailed else 4]
            sections.append(
                SectionDraft(
                    title=truncate(title, 90),
                    start_sec=max(0.0, min(start, duration or start)),
                    end_sec=max(start, min(end, duration or end)),
                    summary=_fix_tech_names(normalize_space(str(item.get("summary") or ""))),
                    key_points=key_points,
                    details=self._clean_details(str(item.get("details") or "")),
                )
            )
        if not sections:
            return None
        sections.sort(key=lambda section: section.start_sec)
        sections[0].start_sec = 0.0
        for left, right in zip(sections, sections[1:]):
            left.end_sec = max(left.start_sec + 5.0, min(left.end_sec, right.start_sec))
            right.start_sec = max(right.start_sec, left.end_sec)
        sections[-1].end_sec = max(
            sections[-1].start_sec + 10.0, duration or sections[-1].end_sec
        )

        limit = 20 if detailed else 12
        keyword_list = [
            normalize_space(str(word)).lower()
            for word in (data.get("keywords") or [])
            if str(word).strip()
        ][:limit]
        if not keyword_list:
            keyword_list = top_keywords(
                [
                    f"{section.title} {' '.join(section.key_points)}"
                    for section in sections
                ],
                limit,
            )

        min_words = Config.API_LLM_SUMMARY_MIN_WORDS if detailed else 45
        max_chars = 2400 if detailed else 700
        if len(summary.split()) < min_words:
            # The model sometimes returns a one-liner; build a compact abstract
            # from the section summaries (no repetition, no section list).
            summary = self._extend_summary(summary, sections, min_words, max_chars)
        if not summary:
            return None

        summary = _fix_tech_names(summary)
        generated_title = normalize_space(str(data.get("title") or "")).strip(' "«»\'.')
        generated_title = generated_title.rstrip(".")
        generated_title = _fix_tech_names(generated_title)
        if not (3 <= len(generated_title) <= 120):
            generated_title = None

        category = normalize_space(str(data.get("category") or "")).strip(' "«»\'.')
        subcategory = normalize_space(str(data.get("subcategory") or "")).strip(' "«»\'.')
        if not (2 <= len(category) <= 100):
            category = None
        if not (2 <= len(subcategory) <= 120):
            subcategory = None

        questions = self._normalize_questions(data.get("questions"))
        if not questions:
            questions = [f"Что такое {word}?" for word in keyword_list[:6]]

        return StudyNotes(
            summary=summary,
            sections=sections,
            keywords=keyword_list,
            llm_used=True,
            mode=mode,
            model=model,
            title=generated_title,
            category=category,
            subcategory=subcategory,
            questions=questions,
        )

    def _extend_summary(
        self,
        summary: str,
        sections: Sequence[SectionDraft],
        target_words: int,
        max_chars: int,
    ) -> str:
        parts = [summary.strip()] if summary.strip() else []
        words = len(summary.split())

        def room() -> bool:
            return words < target_words and sum(len(part) for part in parts) < max_chars

        def add(text: str) -> None:
            nonlocal words
            text = (text or "").strip()
            if not text or text in parts:
                return
            parts.append(text)
            words += len(text.split())

        for section in sections:
            if not room():
                break
            add(section.summary)
        # Section summaries can be empty, duplicated or very short; concrete
        # theses and details still give the abstract the promised volume.
        for section in sections:
            if not room():
                break
            for point in section.key_points:
                if not room():
                    break
                add(point.rstrip(".") + ".")
        for section in sections:
            if not room():
                break
            if section.details:
                add(truncate(section.details, 600))

        text = " ".join(parts)
        if len(text) > max_chars:
            text = truncate(text, max_chars)
        return text

    @staticmethod
    def _normalize_questions(raw) -> list[str]:
        questions: list[str] = []
        for item in raw or []:
            text = normalize_space(str(item))
            if 8 <= len(text) <= 300 and text not in questions:
                questions.append(text if text.endswith("?") else f"{text}?")
            if len(questions) >= 8:
                break
        return questions

    # -- extractive fallback -------------------------------------------
    def _extractive(
        self, *, title: str, segments: Sequence[Segment], duration: float
    ) -> StudyNotes:
        sentences: list[tuple[float, str]] = []
        for segment in segments:
            for sentence in split_sentences(segment.text) or [segment.text]:
                clean = normalize_space(sentence)
                if len(clean) > 25:
                    sentences.append((segment.start_sec, clean))

        weights: dict[str, float] = {}
        for _, sentence in sentences:
            for token in content_tokens(sentence):
                weights[token] = weights.get(token, 0.0) + 1.0
        max_weight = max(weights.values(), default=1.0)

        def score(sentence: str) -> float:
            tokens = content_tokens(sentence)
            if not tokens:
                return 0.0
            total = sum(weights.get(token, 0.0) / max_weight for token in tokens)
            return total / math.sqrt(len(tokens))

        ranked = sorted(
            ((timestamp, sentence) for timestamp, sentence in sentences),
            key=lambda item: score(item[1]),
            reverse=True,
        )[:8]
        summary = " ".join(sentence for _, sentence in sorted(ranked))
        if not summary:
            summary = truncate(" ".join(segment.text for segment in segments), 500)

        keyword_list = top_keywords([segment.text for segment in segments], 12)

        count = max(3, min(8, round((duration or 300) / 420) + 1))
        bucket = max(30.0, (duration or 300) / count)
        sections: list[SectionDraft] = []
        for index in range(count):
            start = index * bucket
            end = min(duration or (start + bucket), (index + 1) * bucket)
            window = [
                sentence
                for timestamp, sentence in sentences
                if start <= timestamp < end
            ]
            if not window and index == count - 1 and sentences:
                window = [sentences[-1][1]]
            if not window:
                continue
            bucket_keywords = top_keywords(window, 4) or keyword_list[:2]
            if index == 0:
                section_title = "Введение"
            elif index == count - 1:
                section_title = "Итоги"
            else:
                section_title = capitalize_first(" · ".join(bucket_keywords[:2])) or f"Раздел {index + 1}"
            best = sorted(window, key=score, reverse=True)[:3]
            sections.append(
                SectionDraft(
                    title=section_title,
                    start_sec=round(start, 2),
                    end_sec=round(end, 2),
                    summary=truncate(" ".join(best[:2]), 260),
                    key_points=[truncate(item, 180) for item in best],
                )
            )
        if not sections:
            sections = [
                SectionDraft(
                    title="Лекция",
                    start_sec=0.0,
                    end_sec=duration or 0.0,
                    summary=truncate(summary, 260),
                    key_points=[truncate(summary, 180)],
                )
            ]
        return StudyNotes(
            summary=summary,
            sections=sections,
            keywords=keyword_list,
            llm_used=False,
            mode=MODE_OFFLINE,
            category=capitalize_first(keyword_list[0]) if keyword_list else "Другое",
            subcategory=sections[0].title if sections else None,
            questions=[f"Что такое {word}?" for word in keyword_list[:6]],
        )

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _safe_mode(mode: str | None) -> str:
        if not mode:
            return default_mode()
        try:
            return normalize_mode(mode)
        except ValueError:
            log.warning("summariser: unknown mode %r, using default", mode)
            return default_mode()

    @staticmethod
    def _target_sections(duration_sec: float) -> int:
        count = round((duration_sec or 300) / 240) + 3
        return max(
            Config.API_LLM_NOTES_MIN_SECTIONS,
            min(Config.API_LLM_NOTES_MAX_SECTIONS, count),
        )

    @staticmethod
    def _emit(on_progress: ProgressCb | None, ratio: float, stage: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(max(0.0, min(1.0, ratio)), stage)
        except Exception:  # pragma: no cover - progress must never break notes
            log.debug("summariser: progress callback failed", exc_info=True)

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        cut = text[:limit].rsplit("\n", 1)[0]
        return f"{cut}\n… (фрагмент сокращён)"

    @staticmethod
    def _merge_windows(
        windows: list[list[Segment]], limit: int
    ) -> list[list[Segment]]:
        step = math.ceil(len(windows) / max(1, limit))
        merged: list[list[Segment]] = []
        for index in range(0, len(windows), step):
            group: list[Segment] = []
            for window in windows[index : index + step]:
                group.extend(window)
            merged.append(group)
        return merged

    @staticmethod
    def _digest(segments: Iterable[Segment], *, max_chars: int) -> str:
        lines: list[str] = []
        used = 0
        for segment in segments:
            line = f"[{clock(segment.start_sec)}] {segment.text}"
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)

    @staticmethod
    def _windows(segments: Sequence[Segment], *, max_chars: int) -> list[list[Segment]]:
        windows: list[list[Segment]] = []
        current: list[Segment] = []
        used = 0
        for segment in segments:
            size = len(segment.text) + 12
            if used + size > max_chars and current:
                windows.append(current)
                current = []
                used = 0
            current.append(segment)
            used += size
        if current:
            windows.append(current)
        return windows


summarizer = Summarizer()
