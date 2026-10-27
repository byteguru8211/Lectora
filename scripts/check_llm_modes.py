"""Diagnostics for the three notes modes (api / local / offline).

Examples
--------
    python scripts/check_llm_modes.py
    python scripts/check_llm_modes.py --mode api
    python scripts/check_llm_modes.py --lecture-id <uuid> --mode api

With ``--lecture-id`` the script rebuilds a conspectus in memory from the
stored transcript (nothing is written to the database), which is the fastest
way to verify the DeepSeek API path without re-transcribing a video.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Config
from app.models import Lecture, TranscriptSegment
from app.services.asr import Segment
from app.services.llm_modes import ALL_MODES, describe_modes
from app.services.summarizer import summarizer
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def print_modes() -> None:
    payload = describe_modes(probe=True)
    print(f"default mode: {payload['default']}")
    for mode in ALL_MODES:
        item = payload["modes"][mode]
        status = "OK" if item["available"] else "OFF"
        print(
            f"  {mode:8s} {status:2s}  model={item.get('model') or '-':22s} "
            f"url={item.get('base_url') or '-':28s} detail={item.get('detail') or '-'}"
        )


def run_notes(lecture_id: str, mode: str) -> None:
    engine = create_engine(Config.DATABASE_URL, future=True)
    try:
        with Session(engine) as session:
            lecture = session.get(Lecture, uuid.UUID(lecture_id))
            if lecture is None:
                raise SystemExit(f"lecture {lecture_id} not found")
            rows = session.execute(
                select(TranscriptSegment)
                .where(TranscriptSegment.lecture_id == lecture.id)
                .order_by(TranscriptSegment.idx)
            ).scalars().all()
            if not rows:
                raise SystemExit("lecture has no transcript yet")

            segments = [
                Segment(start_sec=row.start_sec, end_sec=row.end_sec, text=row.text)
                for row in rows
            ]
            print(
                f"\nlecture: {lecture.title!r} ({lecture.duration_sec:.0f}s, "
                f"{len(segments)} segments, requested mode={mode})"
            )
            started = time.perf_counter()

            def on_progress(ratio: float, stage: str) -> None:
                print(f"  [{ratio * 100:5.1f}%] {stage}", flush=True)

            notes = summarizer.build(
                title="" if lecture.title_auto else lecture.title,
                segments=segments,
                duration_sec=float(lecture.duration_sec or 0.0),
                mode=mode,
                on_progress=on_progress,
            )
            elapsed = time.perf_counter() - started
            print(
                f"\nmode={notes.mode} model={notes.model or '-'} "
                f"elapsed={elapsed:.1f}s sections={len(notes.sections)} "
                f"summary_words={len(notes.summary.split())} "
                f"keywords={len(notes.keywords)} questions={len(notes.questions)}"
            )
            with_details = sum(1 for section in notes.sections if section.details)
            print(f"sections with details: {with_details}/{len(notes.sections)}")
            preview = {
                "title": notes.title,
                "category": notes.category,
                "subcategory": notes.subcategory,
                "summary": notes.summary,
                "keywords": notes.keywords,
                "questions": notes.questions,
                "sections": [
                    {
                        "title": section.title,
                        "start_sec": section.start_sec,
                        "end_sec": section.end_sec,
                        "summary": section.summary,
                        "key_points": section.key_points,
                        "details_chars": len(section.details or ""),
                    }
                    for section in notes.sections
                ],
            }
            out = ROOT / "data" / "llm_modes_check.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"report: {out}")
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lecture-id", help="UUID of a processed lecture")
    parser.add_argument("--mode", default="api", choices=["api", "local", "offline", "extractive"])
    parser.add_argument("--list-only", action="store_true", help="only print mode status")
    args = parser.parse_args()

    print_modes()
    if args.lecture_id and not args.list_only:
        run_notes(args.lecture_id, args.mode)


if __name__ == "__main__":
    main()
