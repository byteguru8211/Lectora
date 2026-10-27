"""Client for a local OpenAI-compatible LLM server (llama.cpp / Ollama / vLLM).

No API keys, no cloud: the backend only talks to ``127.0.0.1``.  If the model
is not running, every caller degrades to a deterministic extractive fallback,
so the product never shows a dead end.

The shared JSON/health contract lives in :mod:`llm_base`; the DeepSeek Web
proxy variant is :class:`app.services.llm_api.ApiLlmClient`.
"""

from __future__ import annotations

import logging
import time

import requests

from ..config import Config
from .llm_base import LlmHealth, LlmUnavailable, OpenAiCompatClient

__all__ = ["LlmUnavailable", "LlmHealth", "LlmClient", "llm"]

log = logging.getLogger(__name__)


class LlmClient(OpenAiCompatClient):
    """Local llama-server client (mode ``local``)."""

    mode = "local"

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
            return LlmHealth(
                False, False, self.base_url, self.model, detail="disabled", mode=self.mode
            )
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
            health = LlmHealth(
                True, ok, self.base_url, self.model, latency, detail, mode=self.mode
            )
        except requests.RequestException as exc:
            health = LlmHealth(
                True, False, self.base_url, self.model, None, type(exc).__name__, mode=self.mode
            )
        self._health_cache = (now, health)
        return health

    # -- generation ----------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: float | None = None,
        **_: object,
    ) -> str:
        if not self.enabled:
            raise LlmUnavailable("LLM disabled", kind="disabled")
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
            raise LlmUnavailable(str(exc), kind="network") from exc

        if response.status_code == 429:
            self._health_cache = None
            raise LlmUnavailable(
                "rate limited", status=429, retry_after=1.5, kind="rate_limit"
            )
        if response.status_code >= 400:
            raise LlmUnavailable(
                f"HTTP {response.status_code}: {response.text[:200]}",
                status=response.status_code,
                kind="request",
            )

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
            "local llm ok %.1fs, %s completion tokens",
            elapsed,
            usage.get("completion_tokens", "?"),
        )
        if not content:
            raise LlmUnavailable("empty completion", kind="empty")
        return content


llm = LlmClient()
