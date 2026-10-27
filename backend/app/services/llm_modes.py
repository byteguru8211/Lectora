"""Three ways to produce notes and answers, behind one selector.

``api``
    DeepSeek Web through the FreeDeepseekAPI proxy — the most detailed output.
``local``
    The llama.cpp model on this machine — no network.
``offline``
    No model at all — deterministic extractive notes (always available).

Fallbacks are intentionally conservative: choosing ``local`` or ``offline``
never silently sends the lecture to a cloud account; only ``api`` may degrade
to the local model, and then to extractive notes.
"""

from __future__ import annotations

import logging

from ..config import Config
from .llm import llm
from .llm_api import api_llm
from .llm_base import LlmHealth

log = logging.getLogger(__name__)

MODE_API = "api"
MODE_LOCAL = "local"
MODE_OFFLINE = "offline"

ALL_MODES: tuple[str, ...] = (MODE_API, MODE_LOCAL, MODE_OFFLINE)

MODE_LABELS = {
    MODE_API: "DeepSeek API",
    MODE_LOCAL: "Локальная модель",
    MODE_OFFLINE: "Офлайн (без ИИ)",
}

MODE_DESCRIPTIONS = {
    MODE_API: "Подробный конспект через DeepSeek Web: больше разделов, тезисов и деталей.",
    MODE_LOCAL: "Модель Qwen на этом компьютере: без интернета, быстрее и компактнее.",
    MODE_OFFLINE: "Без ИИ: структурный конспект по правилам, работает всегда.",
}

_ALIASES = {
    "": MODE_LOCAL,
    "auto": MODE_API,
    "deepseek": MODE_API,
    "ds": MODE_API,
    "llm-api": MODE_API,
    "api-llm": MODE_API,
    "remote": MODE_API,
    "cloud": MODE_API,
    "local-llm": MODE_LOCAL,
    "llm": MODE_LOCAL,
    "qwen": MODE_LOCAL,
    "extractive": MODE_OFFLINE,
    "rules": MODE_OFFLINE,
    "none": MODE_OFFLINE,
    "off": MODE_OFFLINE,
    "no-llm": MODE_OFFLINE,
}


def normalize_mode(value: str | None, default: str | None = None) -> str:
    """Return a valid mode or raise ``ValueError`` for an unknown one."""
    raw = (value or "").strip().lower()
    if not raw:
        raw = (default or Config.LLM_DEFAULT_MODE or MODE_LOCAL).strip().lower()
    raw = _ALIASES.get(raw, raw)
    if raw not in ALL_MODES:
        raise ValueError(f"unknown LLM mode: {value!r}")
    return raw


def default_mode() -> str:
    try:
        return normalize_mode(Config.LLM_DEFAULT_MODE, MODE_LOCAL)
    except ValueError:  # pragma: no cover - misconfiguration guard
        log.warning("invalid LLM_MODE=%r, using local", Config.LLM_DEFAULT_MODE)
        return MODE_LOCAL


def client_for(mode: str):
    """Return the backend instance for a mode, or ``None`` for ``offline``."""
    mode = normalize_mode(mode)
    if mode == MODE_API:
        return api_llm
    if mode == MODE_LOCAL:
        return llm
    return None


def fallback_chain(mode: str) -> list[str]:
    """Ordered modes to try. Cloud is only ever reached from ``api``."""
    mode = normalize_mode(mode)
    if mode == MODE_API:
        return [MODE_API, MODE_LOCAL, MODE_OFFLINE]
    if mode == MODE_LOCAL:
        return [MODE_LOCAL, MODE_OFFLINE]
    return [MODE_OFFLINE]


def resolve_client(mode: str, *, probe: bool = True) -> tuple[str, object | None]:
    """Return ``(mode_used, client)``; ``(offline, None)`` when nothing works."""
    requested = normalize_mode(mode)
    for candidate in fallback_chain(requested):
        client = client_for(candidate)
        if client is None:
            return candidate, None
        if not probe:
            return candidate, client
        try:
            if client.available:
                return candidate, client
        except Exception:  # pragma: no cover - health must never explode
            log.exception("llm: health check failed for %s", candidate)
    if requested != MODE_OFFLINE:
        log.warning("llm: no model available for %s, extractive fallback", requested)
    return MODE_OFFLINE, None


def mode_health(mode: str, *, force: bool = False) -> LlmHealth:
    mode = normalize_mode(mode)
    client = client_for(mode)
    if client is None:
        return LlmHealth(
            enabled=True,
            available=True,
            base_url="",
            model="extractive",
            latency_ms=0,
            detail=None,
            mode=MODE_OFFLINE,
        )
    return client.health(force=force)


def describe_modes(*, probe: bool = True) -> dict:
    """Payload for ``/api/system/info``: every mode with live availability."""
    modes: dict[str, dict] = {}
    for mode in ALL_MODES:
        health = mode_health(mode, force=probe)
        payload = health.as_dict()
        payload.update(
            label=MODE_LABELS[mode],
            description=MODE_DESCRIPTIONS[mode],
            selectable=bool(health.enabled and health.available)
            or mode == MODE_OFFLINE,
        )
        modes[mode] = payload
    return {"default": default_mode(), "modes": modes}
