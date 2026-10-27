"""Shared primitives for OpenAI-compatible LLM clients.

Both the local llama.cpp server and the DeepSeek Web proxy speak the same
``/chat/completions`` dialect, so the transport-independent behaviour lives
here: the error type every caller catches, the health snapshot exposed by the
API, and a JSON-reliable ``chat_json`` built on top of ``chat``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LlmUnavailable(RuntimeError):
    """Raised when an LLM backend cannot serve a request.

    ``kind`` lets callers tell a transient condition (``rate_limit``,
    ``network``) from a permanent one (``auth``, ``context``, ``disabled``) and
    decide whether a retry or a fallback makes sense.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
        kind: str = "unavailable",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.kind = kind

    @property
    def retryable(self) -> bool:
        if self.kind in {"auth", "context", "disabled", "request", "json"}:
            return False
        if self.status is None:
            return self.kind in {"network", "unavailable", "empty", "response"}
        return self.status == 429 or self.status >= 500


@dataclass
class LlmHealth:
    """Read-only health snapshot returned by every backend."""

    enabled: bool
    available: bool
    base_url: str
    model: str
    latency_ms: int | None = None
    detail: str | None = None
    mode: str = "local"
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "available": self.available,
            "base_url": self.base_url,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
            "mode": self.mode,
            "extra": dict(self.extra or {}),
        }


class OpenAiCompatClient:
    """Common contract for a chat-completions backend."""

    mode: str = "local"
    enabled: bool = True
    model: str = ""

    # -- transport -----------------------------------------------------
    def health(self, *, force: bool = False) -> LlmHealth:  # pragma: no cover - abstract
        raise NotImplementedError

    def chat(self, messages: list[dict], **kwargs) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    @property
    def available(self) -> bool:
        return self.health().available

    # -- JSON helpers --------------------------------------------------
    @staticmethod
    def extract_json(raw: str) -> dict | list:
        """Pull the first valid JSON object/array out of a model answer."""
        text = (raw or "").strip()
        fenced = _JSON_FENCE.search(text)
        if fenced:
            text = fenced.group(1).strip()
        for opener, closer in (("{", "}"), ("[", "]")):
            start = text.find(opener)
            end = text.rfind(closer)
            if start != -1 and end > start:
                candidate = text[start : end + 1]
                # strict=False accepts raw newlines/tabs inside JSON strings,
                # which web models emit when writing long markdown details.
                for strict in (True, False):
                    try:
                        return json.loads(candidate, strict=strict)
                    except json.JSONDecodeError:
                        pass
                cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
                for strict in (True, False):
                    try:
                        return json.loads(cleaned, strict=strict)
                    except json.JSONDecodeError:
                        pass
        raise ValueError("no JSON object in model output")

    def chat_json(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        retries: int = 1,
        **kwargs,
    ) -> dict | list:
        """``chat`` + strict JSON extraction with one automatic correction."""
        last_error: Exception | None = None
        attempt_messages = list(messages)
        for attempt in range(retries + 1):
            raw = self.chat(
                attempt_messages,
                max_tokens=max_tokens,
                temperature=0 if attempt else temperature,
                **kwargs,
            )
            try:
                return self.extract_json(raw)
            except ValueError as exc:
                last_error = exc
                log.warning(
                    "%s llm returned non-JSON (attempt %s): %s",
                    self.mode,
                    attempt + 1,
                    (raw or "")[:200],
                )
                attempt_messages = list(messages) + [
                    {
                        "role": "user",
                        "content": (
                            "Ответ должен быть строго валидным JSON без пояснений, "
                            "без markdown-разметки и без текста до/после JSON. "
                            "Повтори ответ только JSON."
                        ),
                    }
                ]
        raise LlmUnavailable(
            f"invalid JSON from model: {last_error}", kind="json"
        )
