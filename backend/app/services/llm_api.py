"""DeepSeek Web client through the local FreeDeepseekAPI proxy.

Why a dedicated client instead of pointing the local client at another port?

* FreeDeepseekAPI drives a **personal DeepSeek web account**, not a metered
  API.  All agents share the account's rate limits and one answer per chat, so
  requests must be serialised, spaced out and retried politely.
* Long prompts are bounded (the proxy starts a fresh chat above
  ``DEEPSEEK_MAX_PROMPT_CHARS`` and drops the middle), so callers get a clear
  ``kind="context"`` error instead of a silently truncated lecture.
* Every request uses an ephemeral agent session key and drops the remote chat
  afterwards: no cross-lecture context leaks, no 100-message chat rot and no
  memory growth in the proxy.

The wire protocol is OpenAI Chat Completions, so the shared
:class:`~app.services.llm_base.OpenAiCompatClient` contract applies unchanged.
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
import uuid
from email.utils import parsedate_to_datetime

import requests

from ..config import Config
from .llm_base import LlmHealth, LlmUnavailable, OpenAiCompatClient

log = logging.getLogger(__name__)

_VERSION_SUFFIX = re.compile(r"/v\d+$")


def _retry_after_seconds(response: requests.Response) -> float | None:
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(raw)
        return max(0.0, moment.timestamp() - time.time())
    except (TypeError, ValueError):
        return None


def _is_rate_limited(response: requests.Response) -> bool:
    """Recognize web-account throttles even when proxy versions return HTTP 200."""
    if response.status_code == 429:
        return True
    try:
        payload = response.json()
    except ValueError:
        return False
    error = payload.get("error") or {}
    message = " ".join(
        str(value) for value in (
            error.get("message", "") if isinstance(error, dict) else error,
            payload.get("message", ""),
            payload.get("biz_code", ""),
            payload.get("code", ""),
        )
    ).lower()
    return any(
        marker in message
        for marker in (
            "too many messages", "rate limit", "rate_limit", "too frequent",
            "account is cooling", "no available account", "all accounts are cooling",
        )
    )


class ApiLlmClient(OpenAiCompatClient):
    """Rate-limited, retrying DeepSeek Web client (mode ``api``)."""

    mode = "api"

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        max_prompt_chars: int | None = None,
        min_interval: float | None = None,
        max_concurrent: int | None = None,
        retries: int | None = None,
        retry_base: float | None = None,
        retry_max: float | None = None,
        queue_timeout: float | None = None,
        session_prefix: str | None = None,
        reset_session: bool | None = None,
    ) -> None:
        self.enabled = Config.API_LLM_ENABLED if enabled is None else bool(enabled)
        self.base_url = (base_url or Config.API_LLM_BASE_URL).rstrip("/")
        self.model = model or Config.API_LLM_MODEL
        self.api_key = Config.API_LLM_KEY if api_key is None else api_key
        self.timeout = float(timeout if timeout is not None else Config.API_LLM_TIMEOUT)
        self.default_max_tokens = int(
            max_tokens if max_tokens is not None else Config.API_LLM_MAX_TOKENS
        )
        self.temperature = float(
            temperature if temperature is not None else Config.API_LLM_TEMPERATURE
        )
        self.max_prompt_chars = int(
            max_prompt_chars
            if max_prompt_chars is not None
            else Config.API_LLM_MAX_PROMPT_CHARS
        )
        self.min_interval = float(
            min_interval if min_interval is not None else Config.API_LLM_MIN_INTERVAL_SEC
        )
        self.max_concurrent = max(
            1,
            int(
                max_concurrent
                if max_concurrent is not None
                else Config.API_LLM_MAX_CONCURRENT
            ),
        )
        self.retries = max(
            1, int(retries if retries is not None else Config.API_LLM_RETRY_ATTEMPTS)
        )
        self.retry_base = float(
            retry_base if retry_base is not None else Config.API_LLM_RETRY_BASE_SEC
        )
        self.retry_max = float(
            retry_max if retry_max is not None else Config.API_LLM_RETRY_MAX_SEC
        )
        self.queue_timeout = float(
            queue_timeout
            if queue_timeout is not None
            else Config.API_LLM_QUEUE_TIMEOUT_SEC
        )
        self.session_prefix = session_prefix or Config.API_LLM_SESSION_PREFIX
        self.reset_sessions = (
            Config.API_LLM_RESET_SESSION if reset_session is None else bool(reset_session)
        )

        self._session = requests.Session()
        self._semaphore = threading.BoundedSemaphore(self.max_concurrent)
        self._rate_lock = threading.Lock()
        self._last_started = 0.0
        self._health_cache: tuple[float, LlmHealth] | None = None
        self._health_ttl = 20.0

    # -- addresses -----------------------------------------------------
    @property
    def root_url(self) -> str:
        """Proxy root (``http://host:port``) without the ``/v1`` suffix."""
        return _VERSION_SUFFIX.sub("", self.base_url)

    @property
    def chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"

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
        extra: dict = {}
        detail: str | None = None
        available = False
        try:
            response = self._session.get(f"{self.root_url}/health", timeout=3.0)
            latency = int((time.perf_counter() - started) * 1000)
            if response.status_code != 200:
                latency, available, detail = self._models_probe()
            else:
                payload = response.json() if response.content else {}
                accounts = payload.get("accounts") or []
                ready = [item for item in accounts if item.get("ready")]
                models = payload.get("models") or []
                model_ok = not models or self.model in models
                available = bool(ready or not accounts) and model_ok and bool(
                    payload.get("config_ready", True)
                )
                if not accounts:
                    detail = "нет настроенных аккаунтов DeepSeek"
                elif not ready:
                    detail = "аккаунт DeepSeek на кулдауне"
                elif not model_ok:
                    detail = f"модель {self.model} не поддерживается прокси"
                extra = {
                    "accounts": len(accounts),
                    "ready_accounts": len(ready),
                    "in_flight": payload.get("in_flight"),
                    "models_available": len(models),
                    "service": payload.get("service"),
                }
        except (requests.RequestException, ValueError):
            # Older/degraded proxies and the official API have no /health.
            latency, available, detail = self._models_probe()

        health = LlmHealth(
            True,
            available,
            self.base_url,
            self.model,
            latency,
            detail,
            mode=self.mode,
            extra=extra,
        )
        # Do not cache hard failures for long: the account may recover quickly.
        self._health_cache = (now, health)
        return health

    def _models_probe(self) -> tuple[int, bool, str | None]:
        started = time.perf_counter()
        try:
            response = self._session.get(f"{self.base_url}/models", timeout=2.5)
            latency = int((time.perf_counter() - started) * 1000)
            ok = response.status_code == 200
            return latency, ok, None if ok else f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            latency = int((time.perf_counter() - started) * 1000)
            return latency, False, type(exc).__name__

    # -- scheduling ----------------------------------------------------
    def _throttle(self) -> None:
        """Keep at least ``min_interval`` seconds between request starts."""
        if self.min_interval <= 0:
            return
        with self._rate_lock:
            wait = self.min_interval - (time.monotonic() - self._last_started)
            if wait > 0:
                time.sleep(wait)
            self._last_started = time.monotonic()

    def _backoff(self, attempt: int) -> float:
        delay = self.retry_base * (2 ** max(0, attempt - 1))
        delay += random.uniform(0.0, min(2.0, delay * 0.25))
        return min(self.retry_max, delay)

    def _new_session_key(self) -> str:
        return f"{self.session_prefix}-{uuid.uuid4().hex[:12]}"

    def reset_session(self, agent: str) -> bool:
        """Drop the remote DeepSeek chat for an agent (best effort)."""
        if not self.reset_sessions or not agent:
            return False
        try:
            response = self._session.post(
                f"{self.root_url}/reset-session",
                params={"agent": agent},
                timeout=5.0,
            )
            return response.status_code < 400
        except requests.RequestException as exc:  # pragma: no cover - diagnostics only
            log.debug("api llm: session reset failed (%s)", exc)
            return False

    # -- generation ----------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: float | None = None,
        session_key: str | None = None,
        keep_session: bool = False,
        **_: object,
    ) -> str:
        """Send one completion, retrying only transient failures.

        ``session_key`` pins the request to a named proxy session; by default a
        throw-away key is used and the remote chat is reset afterwards, which
        keeps every lecture/task isolated.
        """
        if not self.enabled:
            raise LlmUnavailable("DeepSeek API disabled", kind="disabled")

        prompt_chars = sum(len(str(message.get("content") or "")) for message in messages)
        if prompt_chars > self.max_prompt_chars:
            raise LlmUnavailable(
                f"prompt too long: {prompt_chars} > {self.max_prompt_chars} chars",
                kind="context",
            )

        ephemeral = session_key is None and not keep_session
        key = session_key or self._new_session_key()
        try:
            last_error: LlmUnavailable | None = None
            for attempt in range(1, self.retries + 1):
                try:
                    return self._request_once(
                        messages,
                        session_key=key,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        timeout=timeout,
                    )
                except LlmUnavailable as exc:
                    last_error = exc
                    if not exc.retryable or attempt >= self.retries:
                        raise
                    delay = exc.retry_after or self._backoff(attempt)
                    log.warning(
                        "api llm retry %d/%d in %.1fs (%s)",
                        attempt,
                        self.retries - 1,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
            raise last_error or LlmUnavailable("api llm failed", kind="unavailable")
        finally:
            if ephemeral:
                self.reset_session(key)

    def _request_once(
        self,
        messages: list[dict],
        *,
        session_key: str,
        max_tokens: int | None,
        temperature: float | None,
        timeout: float | None,
    ) -> str:
        if not self._semaphore.acquire(timeout=self.queue_timeout):
            raise LlmUnavailable(
                f"no free DeepSeek slot after {self.queue_timeout:.0f}s", kind="busy"
            )
        try:
            self._throttle()
            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens or self.default_max_tokens,
                "temperature": self.temperature if temperature is None else temperature,
                "stream": False,
                # FreeDeepseekAPI keys its remote chat by this value.
                "user": session_key,
            }
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            started = time.perf_counter()
            try:
                response = self._session.post(
                    self.chat_url,
                    json=payload,
                    headers=headers,
                    timeout=timeout or self.timeout,
                )
            except requests.RequestException as exc:
                self._health_cache = None
                raise LlmUnavailable(str(exc), kind="network") from exc

            if _is_rate_limited(response):
                self._health_cache = None
                raise LlmUnavailable(
                    "DeepSeek account rate limit",
                    status=429,
                    retry_after=_retry_after_seconds(response),
                    kind="rate_limit",
                )

            if response.status_code in (401, 403):
                self._health_cache = None
                raise LlmUnavailable(
                    f"{response.status_code}: {response.text[:200]}",
                    status=response.status_code,
                    kind="auth",
                )
            if response.status_code >= 500:
                self._health_cache = None
                raise LlmUnavailable(
                    f"HTTP {response.status_code}: {response.text[:200]}",
                    status=response.status_code,
                    kind="server",
                )
            if response.status_code >= 400:
                body = response.text[:300]
                kind = "context" if "context" in body.lower() or "too long" in body.lower() else "request"
                raise LlmUnavailable(
                    f"HTTP {response.status_code}: {body}",
                    status=response.status_code,
                    kind=kind,
                )

            try:
                data = response.json()
            except ValueError as exc:
                raise LlmUnavailable("invalid JSON response", kind="response") from exc

            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = (message.get("content") or "").strip()
            if not content:
                content = (message.get("reasoning_content") or "").strip()
            elapsed = time.perf_counter() - started
            usage = data.get("usage") or {}
            log.info(
                "api llm ok %.1fs, %s chars, %s completion tokens%s",
                elapsed,
                len(content),
                usage.get("completion_tokens", "?"),
                f", finish={choice.get('finish_reason')}"
                if choice.get("finish_reason") not in (None, "stop")
                else "",
            )
            if not content:
                raise LlmUnavailable("empty completion", kind="empty")
            return content
        finally:
            self._semaphore.release()


api_llm = ApiLlmClient()
