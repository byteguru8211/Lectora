"""Client for a local OpenAI-compatible LLM server (llama.cpp / Ollama / vLLM).

No API keys, no cloud: the backend only talks to ``127.0.0.1``.  If the model
is not running, every caller degrades to a deterministic extractive fallback,
so the product never shows a dead end.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

import requests

from ..config import Config

log = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LlmUnavailable(RuntimeError):
    """Raised when the local model server cannot be reached."""


@dataclass
class LlmHealth:
    enabled: bool
    available: bool
    base_url: str
    model: str
    latency_ms: int | None = None
    detail: str | None = None

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "available": self.available,
            "base_url": self.base_url,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
        }


class LlmClient:
    def __init__(self) -> None:
        self.base_url = Config.LLM_BASE_URL
        self.model = Config.LLM_MODEL
        self.enabled = Config.LLM_ENABLED
        self.timeout = Config.LLM_TIMEOUT
        self._session = requests.Session()
        self._health_cache: tuple[float, LlmHealth] | None = None
        self._health_ttl = 20.0

    # -- health --------------------------------------------------------
    def health(self, *, force: bool = False) -> LlmHealth:
        if not self.enabled:
            return LlmHealth(False, False, self.base_url, self.model, detail="disabled")
        now = time.monotonic()
        if (
            not force
            and self._health_cache
            and now - self._health_cache[0] < self._health_ttl
        ):
            return self._health_cache[1]
        started = time.perf_counter()
        try:
            response = self._session.get(f"{self.base_url}/models", timeout=2.5)
            latency = int((time.perf_counter() - started) * 1000)
            ok = response.status_code == 200
            detail = None if ok else f"HTTP {response.status_code}"
            health = LlmHealth(True, ok, self.base_url, self.model, latency, detail)
        except requests.RequestException as exc:
            health = LlmHealth(
                True, False, self.base_url, self.model, None, type(exc).__name__
            )
        self._health_cache = (now, health)
        return health

    @property
    def available(self) -> bool:
        return self.health().available

    # -- generation ----------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> str:
        if not self.enabled:
            raise LlmUnavailable("LLM disabled")
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or Config.LLM_MAX_TOKENS,
            "temperature": Config.LLM_TEMPERATURE if temperature is None else temperature,
            "stream": False,
            "stop": ["<|im_end|>"],
        }
        started = time.perf_counter()
        try:
            response = self._session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=timeout or self.timeout,
                headers={"Authorization": f"Bearer {Config.LLM_API_KEY}"},
            )
        except requests.RequestException as exc:
            self._health_cache = None
            raise LlmUnavailable(str(exc)) from exc

        if response.status_code == 429:
            time.sleep(1.5)
            raise LlmUnavailable("rate limited")
        if response.status_code >= 400:
            raise LlmUnavailable(f"HTTP {response.status_code}: {response.text[:200]}")

        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = (message.get("content") or "").strip()
        # Qwen3-style servers may put the answer in reasoning_content
        if not content:
            content = (message.get("reasoning_content") or "").strip()
        elapsed = time.perf_counter() - started
        usage = data.get("usage") or {}
        log.info(
            "llm ok %.1fs, %s completion tokens",
            elapsed,
            usage.get("completion_tokens", "?"),
        )
        if not content:
            raise LlmUnavailable("empty completion")
        return content

    # -- JSON helpers --------------------------------------------------
    @staticmethod
    def extract_json(raw: str) -> dict | list:
        text = raw.strip()
        fenced = _JSON_FENCE.search(text)
        if fenced:
            text = fenced.group(1).strip()
        for opener, closer in (("{", "}"), ("[", "]")):
            start = text.find(opener)
            end = text.rfind(closer)
            if start != -1 and end > start:
                candidate = text[start : end + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
                    try:
                        return json.loads(cleaned)
                    except json.JSONDecodeError:
                        continue
        raise ValueError("no JSON object in model output")

    def chat_json(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        retries: int = 1,
    ) -> dict | list:
        last_error: Exception | None = None
        attempt_messages = list(messages)
        for attempt in range(retries + 1):
            raw = self.chat(
                attempt_messages,
                max_tokens=max_tokens,
                temperature=0 if attempt else temperature,
            )
            try:
                return self.extract_json(raw)
            except ValueError as exc:
                last_error = exc
                log.warning("LLM returned non-JSON (attempt %s): %s", attempt + 1, raw[:200])
                attempt_messages = list(messages) + [
                    {
                        "role": "user",
                        "content": "Ответ должен быть строго валидным JSON без пояснений. "
                        "Повтори ответ только JSON.",
                    }
                ]
        raise LlmUnavailable(f"invalid JSON from model: {last_error}")


llm = LlmClient()
