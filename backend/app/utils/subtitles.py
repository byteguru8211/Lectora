"""Shared WebVTT / SubRip serialisation for transcript segments."""

from __future__ import annotations

from typing import Iterable

from .timefmt import srt_time, vtt_time


def build_subtitles(
    segments: Iterable,
    *,
    language: str,
    target_language: str | None,
    requested: str,
    fmt: str = "vtt",
) -> str:
    """Render segments in the requested language as VTT or SRT.

    The caller validates that ``requested`` is one of the available languages.
    """
    use_translation = bool(target_language and requested == target_language)
    lines: list[str] = [] if fmt == "srt" else ["WEBVTT", ""]
    if fmt == "srt":
        for index, row in enumerate(segments, start=1):
            value = row.translated_text if use_translation else row.text
            text = (value or row.text).replace("-->", "->")
            lines.extend(
                [
                    str(index),
                    f"{srt_time(row.start_sec)} --> {srt_time(row.end_sec)}",
                    text,
                    "",
                ]
            )
        return "\n".join(lines)
    for row in segments:
        value = row.translated_text if use_translation else row.text
        text = (value or row.text).replace("-->", "->")
        lines.extend([f"{vtt_time(row.start_sec)} --> {vtt_time(row.end_sec)}", text, ""])
    return "\n".join(lines)
