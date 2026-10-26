"""Lecture notes: abstract, outline with timestamps, keywords.

Two strategies, one contract:
* **LLM** (default when llama-server is up) — map-reduce over the transcript,
  JSON-only output, strictly validated afterwards.
* **Extractive** (always available) — sentence scoring + time buckets, so the
  outline and abstract exist even with no model running.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from ..config import Config
from ..utils.text import (
    capitalize_first,
    content_tokens,
    keywords as top_keywords,
    normalize_space,
    split_sentences,
    truncate,
)
from ..utils.timefmt import clock, format_timestamp, parse_timestamp
from .asr import Segment
from .llm import LlmUnavailable, llm

log = logging.getLogger(__name__)

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


@dataclass
class SectionDraft:
    title: str
    start_sec: float
    end_sec: float
    summary: str = ""
    key_points: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "start_sec": round(self.start_sec, 2),
            "end_sec": round(self.end_sec, 2),
            "summary": self.summary,
            "key_points": self.key_points,
            "timestamp": format_timestamp(self.start_sec),
        }


@dataclass
class StudyNotes:
    summary: str
    sections: list[SectionDraft]
    keywords: list[str]
    llm_used: bool
    model: str | None = None
    title: str | None = None


class Summarizer:
    # -- public API ----------------------------------------------------
    def build(
        self,
        *,
        title: str,
        segments: Sequence[Segment],
        duration_sec: float,
    ) -> StudyNotes:
        if not segments:
            raise ValueError("no segments to summarise")

        fallback = self._extractive(title=title, segments=segments, duration=duration_sec)
        if not Config.LLM_ENABLED or not llm.available:
            log.info("summariser: LLM unavailable, using extractive notes")
            return fallback

        try:
            notes = self._llm_notes(title=title, segments=segments, duration_sec=duration_sec)
            if notes and notes.sections:
                log.info("summariser: LLM notes ready (%d sections)", len(notes.sections))
                return notes
        except LlmUnavailable as exc:
            log.warning("summariser: LLM failed (%s), extractive fallback", exc)
        except Exception:
            log.exception("summariser: unexpected failure, extractive fallback")

        return fallback

    # -- LLM path -------------------------------------------------------
    def _llm_notes(
        self, *, title: str, segments: Sequence[Segment], duration_sec: float
    ) -> StudyNotes | None:
        digest = self._digest(segments, max_chars=Config.SUMMARY_MAX_INPUT_CHARS)
        if not digest:
            return None

        if len(digest) <= Config.SUMMARY_MAX_INPUT_CHARS:
            payload = self._reduce_payload(title, digest, duration_sec)
        else:  # pragma: no cover - only for very long lectures
            notes = self._map_notes(segments)
            payload = self._reduce_payload(title, json.dumps(notes, ensure_ascii=False), duration_sec)

        data = llm.chat_json(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": payload},
            ],
            max_tokens=Config.LLM_MAX_TOKENS,
            temperature=0.2,
        )
        if not isinstance(data, dict):
            return None
        notes = self._validate(data, duration_sec)
        if notes is not None and len(notes.sections) < 3:
            # The model sometimes returns 2 broad chapters; ask once for a proper outline.
            log.info("summariser: only %d sections, retrying", len(notes.sections))
            try:
                retry = llm.chat_json(
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
                    retried = self._validate(retry, duration_sec)
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
        """Map phase for lectures longer than the context window."""
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
    def _validate(self, data: dict, duration: float) -> StudyNotes | None:
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
            ][:4]
            sections.append(
                SectionDraft(
                    title=truncate(title, 90),
                    start_sec=max(0.0, min(start, duration or start)),
                    end_sec=max(start, min(end, duration or end)),
                    summary=_fix_tech_names(normalize_space(str(item.get("summary") or ""))),
                    key_points=key_points,
                )
            )
        if not sections:
            return None
        sections.sort(key=lambda s: s.start_sec)
        sections[0].start_sec = 0.0
        for left, right in zip(sections, sections[1:]):
            left.end_sec = max(left.start_sec + 5.0, min(left.end_sec, right.start_sec))
            right.start_sec = max(right.start_sec, left.end_sec)
        sections[-1].end_sec = max(sections[-1].start_sec + 10.0, duration or sections[-1].end_sec)

        keyword_list = [
            normalize_space(str(word)).lower()
            for word in (data.get("keywords") or [])
            if str(word).strip()
        ][:12]
        if not keyword_list:
            keyword_list = top_keywords([segment.text for segment in []], 10)
        if not summary:
            summary = " ".join(
                point for section in sections[:3] for point in section.key_points[:1]
            )[:600]
        if len(summary.split()) < 45:
            # The model sometimes returns a one-liner; build a compact abstract
            # from the first section summaries (no repetition, no section list).
            parts = [summary.strip()] if summary else []
            for section in sections[:2]:
                text = (section.summary or "").strip()
                if text and text not in parts:
                    parts.append(text)
            summary = " ".join(parts)[:700]
        if not summary:
            return None

        summary = _fix_tech_names(summary)
        generated_title = normalize_space(str(data.get("title") or "")).strip(' "«»\'.')
        generated_title = generated_title.rstrip(".")
        generated_title = _fix_tech_names(generated_title)
        if not (3 <= len(generated_title) <= 120):
            generated_title = None

        return StudyNotes(
            summary=summary,
            sections=sections,
            keywords=keyword_list,
            llm_used=True,
            model=Config.LLM_MODEL,
            title=generated_title,
        )

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
        )[:6]
        summary = " ".join(sentence for _, sentence in sorted(ranked))
        if not summary:
            summary = truncate(" ".join(segment.text for segment in segments), 500)

        keyword_list = top_keywords([segment.text for segment in segments], 10)

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
        )

    # -- helpers --------------------------------------------------------
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
