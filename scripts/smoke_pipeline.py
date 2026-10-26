"""Dev smoke test: run the whole pipeline on a local file without the HTTP layer.

Usage:
    .venv\\Scripts\\python.exe scripts\\smoke_pipeline.py videos_examples\\пример_1.mp4
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

os.environ.setdefault("START_WORKER", "0")

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Lecture, Section  # noqa: E402
from app.services.pipeline import get_pipeline  # noqa: E402
from app.services.search import search_service  # noqa: E402


def main() -> int:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "videos_examples/пример_1.mp4")
    if not source.is_file():
        print(f"file not found: {source}")
        return 2

    app = create_app()
    storage = app.extensions["storage"]
    pipeline = get_pipeline(storage)

    session = db.session()
    try:
        key = storage.new_key()
        directory = storage.lecture_dir(key)
        target = directory / "original.mp4"
        target.write_bytes(source.read_bytes())
        lecture = Lecture(
            storage_key=key,
            title=source.stem,
            source_type="upload",
            original_filename=source.name,
            asr_profile="accurate",
            video_path=storage.relative(target),
            status="queued",
            stage="queued",
        )
        session.add(lecture)
        session.commit()
        print(f"lecture {lecture.id} created, running pipeline…")

        pipeline.process(session, lecture.id, None)
        session.expire_all()
        lecture = session.get(Lecture, lecture.id)
        print(f"status={lecture.status} stage={lecture.stage} progress={lecture.progress}")
        print(f"duration={lecture.duration_sec}s words={lecture.word_count} "
              f"segments={lecture.segment_count} chunks={lecture.chunk_count}")
        print(f"llm_model={lecture.llm_model}")
        print(f"summary: {(lecture.summary or '')[:400]}")
        sections = (
            session.query(Section)
            .filter(Section.lecture_id == lecture.id)
            .order_by(Section.idx)
            .all()
        )
        for section in sections:
            print(f"  [{section.start_sec:.0f}-{section.end_sec:.0f}] {section.title} :: "
                  f"{(section.summary or '')[:80]}")
        print(f"keywords: {lecture.keywords}")

        if lecture.status != "ready":
            print(f"ERROR: {lecture.error_message}")
            return 1

        for query in ("объяснение теоремы пифагора", "как работает алгоритм", "пример из жизни"):
            outcome = search_service.search(session, query, lecture_ids=[lecture.id], limit=3)
            print(f"\nquery: {query} ({outcome.took_ms} ms, reranked={outcome.reranked})")
            for hit in outcome.hits:
                print(f"  {hit.timestamp} [{hit.scores.get('final', 0):.3f}] {hit.text[:120]}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
