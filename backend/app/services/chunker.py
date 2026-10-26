"""Grouping transcript segments into semantic retrieval chunks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass
class TimedText:
    start_sec: float
    end_sec: float
    text: str


@dataclass
class BuiltChunk:
    start_sec: float
    end_sec: float
    text: str
    token_count: int


def build_chunks(
    segments: Sequence[TimedText],
    *,
    max_chars: int = 1200,
    max_sec: float = 60.0,
    overlap_segments: int = 1,
    min_chars: int = 140,
) -> list[BuiltChunk]:
    """Merge consecutive segments into ~1 KB windows with a small overlap.

    Overlap keeps answers that straddle a boundary retrievable, while the
    character cap keeps embedding quality high (bge-m3 likes focused windows).
    """
    if not segments:
        return []

    chunks: list[BuiltChunk] = []
    current: list[TimedText] = []
    current_chars = 0
    started_at = segments[0].start_sec

    def flush() -> None:
        nonlocal current, current_chars, started_at
        if not current:
            return
        text = " ".join(seg.text.strip() for seg in current).strip()
        if text:
            chunks.append(
                BuiltChunk(
                    start_sec=round(current[0].start_sec, 2),
                    end_sec=round(current[-1].end_sec, 2),
                    text=text,
                    token_count=max(1, len(text) // 4),
                )
            )
        tail = current[-overlap_segments:] if overlap_segments > 0 else []
        current = [seg for seg in tail if seg.end_sec - tail[0].start_sec < max_sec / 2]
        current_chars = sum(len(seg.text) + 1 for seg in current)
        started_at = current[0].start_sec if current else 0.0

    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        projected = current_chars + len(text) + 1
        too_long = projected > max_chars
        too_wide = current and (segment.end_sec - current[0].start_sec) > max_sec
        if (too_long or too_wide) and current:
            flush()
        current.append(segment)
        current_chars += len(text) + 1
        if len(current) == 1:
            started_at = segment.start_sec

    if current and current_chars >= min_chars or (current and not chunks):
        flush()
    elif current and chunks:
        # tiny tail: attach to the previous chunk instead of a 20-char orphan
        tail_text = " ".join(seg.text.strip() for seg in current).strip()
        if tail_text and not chunks[-1].text.endswith(tail_text):
            chunks[-1].text = f"{chunks[-1].text} {tail_text}".strip()
            chunks[-1].end_sec = round(current[-1].end_sec, 2)
            chunks[-1].token_count = max(1, len(chunks[-1].text) // 4)

    return chunks


def segments_to_text(segments: Iterable[TimedText], separator: str = " ") -> str:
    return separator.join(seg.text.strip() for seg in segments if seg.text.strip())
