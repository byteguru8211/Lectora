"""Command-line utilities: init-db, ingest, list, stats.

Usage:
    .venv\\Scripts\\python.exe backend\\manage.py init-db
    .venv\\Scripts\\python.exe backend\\manage.py ingest videos_examples\\пример_1.mp4 --title "Геометрия"
    .venv\\Scripts\\python.exe backend\\manage.py stats
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("START_WORKER", "0")
os.environ.setdefault("WARMUP", "0")

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Lecture  # noqa: E402
from app.services.pipeline import get_pipeline  # noqa: E402
from app.services.search import search_service  # noqa: E402
from app.utils.timefmt import format_timestamp  # noqa: E402


def cmd_init_db(_args) -> int:
    create_app()
    print("Схема базы данных готова.")
    return 0


def cmd_ingest(args) -> int:
    source = Path(args.path)
    if not source.is_file():
        print(f"Файл не найден: {source}")
        return 2
    app = create_app()
    storage = app.extensions["storage"]
    pipeline = get_pipeline(storage)

    key = storage.new_key()
    directory = storage.lecture_dir(key)
    target = directory / f"original{source.suffix.lower() or '.mp4'}"
    target.write_bytes(source.read_bytes())

    session = db.session()
    try:
        lecture = Lecture(
            storage_key=key,
            title=args.title or source.stem,
            description=args.description,
            source_type="upload",
            original_filename=source.name,
            asr_profile=args.profile,
            video_path=storage.relative(target),
            status="queued",
            stage="queued",
        )
        session.add(lecture)
        session.commit()
        print(f"Лекция {lecture.id} создана, обрабатываем…")
        started = time.perf_counter()
        pipeline.process(session, lecture.id, None)
        session.expire_all()
        lecture = session.get(Lecture, lecture.id)
        elapsed = time.perf_counter() - started
        print(f"Статус: {lecture.status}, {elapsed:.0f} c")
        if lecture.status != "ready":
            print(f"Ошибка: {lecture.error_message}")
            return 1
        print(
            f"{lecture.word_count} слов, {lecture.segment_count} субтитров, "
            f"{lecture.chunk_count} фрагментов, длительность {format_timestamp(lecture.duration_sec)}"
        )
        print(f"Конспект ({'LLM' if lecture.llm_model else 'экстрактивный'}):")
        print((lecture.summary or "")[:600])
        search_service.invalidate(lecture.id)
        return 0
    finally:
        session.close()


def cmd_list(_args) -> int:
    create_app()
    session = db.session()
    try:
        rows = session.query(Lecture).order_by(Lecture.created_at.desc()).all()
        if not rows:
            print("Лекций пока нет.")
            return 0
        for lecture in rows:
            marker = "LLM" if lecture.llm_model else "ext"
            print(
                f"{lecture.id}  {lecture.status:10s}  "
                f"{format_timestamp(lecture.duration_sec):>7s}  "
                f"{lecture.chunk_count:4d} фрагм.  [{marker}]  {lecture.title}"
            )
        return 0
    finally:
        session.close()


def cmd_stats(_args) -> int:
    app = create_app()
    session = db.session()
    try:
        total = session.query(Lecture).count()
        ready = session.query(Lecture).filter(Lecture.status == "ready").count()
        chunks = sum(lecture.chunk_count or 0 for lecture in session.query(Lecture).all())
        duration = sum(lecture.duration_sec or 0 for lecture in session.query(Lecture).all())
        print(f"Лекций: {total} (готовых {ready})")
        print(f"Суммарная длительность: {format_timestamp(duration)}")
        print(f"Смысловых фрагментов: {chunks}")
        print(f"Хранилище: {app.config['STORAGE_DIR']}")
        return 0
    finally:
        session.close()


def cmd_requeue(_args) -> int:
    app = create_app()
    runner = app.extensions["job_runner"]
    runner.recover()
    print("Очередь восстановлена, незавершённые задачи перезапущены воркером.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Lectora CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="создать таблицы и индексы").set_defaults(func=cmd_init_db)
    sub.add_parser("list", help="список лекций").set_defaults(func=cmd_list)
    sub.add_parser("stats", help="сводная статистика").set_defaults(func=cmd_stats)
    sub.add_parser("requeue", help="перезапустить незавершённые задачи").set_defaults(func=cmd_requeue)

    ingest = sub.add_parser("ingest", help="обработать локальный видеофайл")
    ingest.add_argument("path")
    ingest.add_argument("--title", default=None)
    ingest.add_argument("--description", default=None)
    ingest.add_argument("--profile", choices=["accurate", "fast"], default="accurate")
    ingest.set_defaults(func=cmd_ingest)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
