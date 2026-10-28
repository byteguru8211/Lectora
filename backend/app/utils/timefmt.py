"""Time formatting helpers (used by API payloads and the LLM prompts)."""

from __future__ import annotations

import re

_TIME_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?$")


def format_timestamp(seconds: float | None) -> str:
    """``3725.4`` -> ``"1:02:05"``; ``95`` -> ``"1:35"``."""
    if seconds is None:
        return "0:00"
    total = max(0, int(round(float(seconds))))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def clock(seconds: float | None) -> str:
    """``3725`` -> ``"01:02:05"`` (stored in captions and prompts)."""
    total = max(0, int(round(float(seconds or 0))))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_timestamp(value: str | int | float | None) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _TIME_RE.match(str(value).strip())
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    secs = int(match.group(3))
    frac = float(f"0.{match.group(4)}") if match.group(4) else 0.0
    return hours * 3600 + minutes * 60 + secs + frac


def vtt_time(seconds: float) -> str:
    """WebVTT timestamp: ``00:01:02.500``."""
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def srt_time(seconds: float) -> str:
    """SubRip timestamp: ``00:01:02,500``."""
    return vtt_time(seconds).replace(".", ",")
