"""Grounded Q&A over a single lecture (RAG with timestamped citations).

The answer backend follows the lecture's notes mode: ``api`` uses DeepSeek Web
(detailed answers), ``local`` the llama.cpp model, and any unavailable backend
degrades to a transcript-grounded extractive answer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..models import Lecture
from ..utils.text import truncate
from ..utils.timefmt import format_timestamp
from .llm import LlmUnavailable
from .llm_modes import (
    MODE_API,
    MODE_OFFLINE,
    default_mode,
    normalize_mode,
    resolve_client,
)
from .search import SearchHit, search_service

log = logging.getLogger(__name__)

_SYSTEM = (
    "Ты — внимательный преподаватель-ассистент. Отвечай на русском языке, опираясь "
    "ТОЛЬКО на фрагменты лекции, которые тебе дали. Если во фрагментах нет ответа, "
    "честно скажи, что в лекции это не прозвучало, и предложи, что поискать. "
    "Не выдумывай факты, формулы и числа. Пиши кратко: 2-5 предложений, без "
    "markdown-заголовков и без списков, если не просили."
)

_API_SYSTEM = (
    "Ты — внимательный преподаватель-ассистент. Отвечай на русском языке, опираясь "
    "ТОЛЬКО на фрагменты лекции, которые тебе дали. Если во фрагментах нет ответа, "
    "честно скажи, что в лекции это не прозвучало, и предложи, что поискать. "
    "Не выдумывай факты, формулы и числа. Отвечай подробно и по делу: 4-8 "
    "предложений, при необходимости — коротким списком или формулой. Можешь "
    "ссылаться на таймкоды фрагментов."
)


@dataclass
class QaAnswer:
    answer: str
    citations: list[dict]
    llm_used: bool
    grounded: bool
    mode: str = MODE_OFFLINE

    def as_dict(self) -> dict:
        return {
            "answer": self.answer,
            "citations": self.citations,
            "llm_used": self.llm_used,
            "grounded": self.grounded,
            "mode": self.mode,
        }


class QaService:
    def ask(self, session, lecture: Lecture, question: str, *, limit: int = 6) -> QaAnswer:
        outcome = search_service.search(
            session,
            question,
            lecture_ids=[lecture.id],
            limit=limit,
            use_rerank=True,
        )
        hits: list[SearchHit] = outcome.hits
        citations = [self._citation(hit) for hit in hits[:4]]

        if not hits:
            return QaAnswer(
                answer=(
                    "В этой лекции не нашлось фрагментов по вашему вопросу. "
                    "Попробуйте переформулировать или искать по всему курсу."
                ),
                citations=[],
                llm_used=False,
                grounded=True,
                mode=MODE_OFFLINE,
            )

        requested = self._lecture_mode(lecture)
        mode, client = resolve_client(requested)
        if client is None:
            return QaAnswer(
                answer=self._extractive(question, hits),
                citations=citations,
                llm_used=False,
                grounded=False,
                mode=MODE_OFFLINE,
            )

        context = "\n\n".join(
            f"[{index}] {hit.timestamp} — {hit.text}" for index, hit in enumerate(hits, start=1)
        )
        system = _API_SYSTEM if mode == MODE_API else _SYSTEM
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Вопрос: {question}\n\nФрагменты лекции «{lecture.title}»:\n{context}\n\n"
                    "Ответь на вопрос по этим фрагментам."
                ),
            },
        ]
        try:
            answer = client.chat(
                messages,
                max_tokens=1200 if mode == MODE_API else 420,
                temperature=0.15,
            )
            return QaAnswer(
                answer=answer.strip(),
                citations=citations,
                llm_used=True,
                grounded=True,
                mode=mode,
            )
        except LlmUnavailable as exc:
            log.warning("qa: %s model failed (%s), extractive answer", mode, exc)
            return QaAnswer(
                answer=self._extractive(question, hits),
                citations=citations,
                llm_used=False,
                grounded=False,
                mode=MODE_OFFLINE,
            )

    @staticmethod
    def _lecture_mode(lecture: Lecture) -> str:
        try:
            return normalize_mode(getattr(lecture, "llm_mode", None) or default_mode())
        except ValueError:
            return default_mode()

    @staticmethod
    def _citation(hit: SearchHit) -> dict:
        return {
            "lecture_id": hit.lecture_id,
            "lecture_title": hit.lecture_title,
            "start_sec": round(hit.start_sec, 2),
            "end_sec": round(hit.end_sec, 2),
            "timestamp": format_timestamp(hit.start_sec),
            "text": truncate(hit.text, 220),
        }

    @staticmethod
    def _extractive(question: str, hits: list[SearchHit]) -> str:
        best = hits[:3]
        lines = [f"LLM недоступна, поэтому показываю найденные фрагменты по запросу «{question}»:"]
        for hit in best:
            lines.append(f"• {hit.timestamp} — {truncate(hit.text, 260)}")
        lines.append(
            "Включите локальную модель или DeepSeek API, чтобы получать связный ответ."
        )
        return "\n".join(lines)


qa_service = QaService()
