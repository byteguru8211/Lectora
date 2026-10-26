"""Crash-safe background worker backed by the ``jobs`` table."""

from __future__ import annotations

import logging
import threading
import time
import uuid

from sqlalchemy import select, update

from ..models import Job, Lecture, utcnow
from .pipeline import Pipeline

log = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, db, pipeline: Pipeline, *, threads: int = 1) -> None:
        self.db = db
        self.pipeline = pipeline
        self.threads = max(1, threads)
        self._stop = threading.Event()
        self._workers: list[threading.Thread] = []
        self._started = False

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.recover()
        for index in range(self.threads):
            worker = threading.Thread(
                target=self._loop, name=f"lectora-worker-{index}", daemon=True
            )
            worker.start()
            self._workers.append(worker)
        log.info("job runner started (%d thread(s))", self.threads)

    def stop(self) -> None:
        self._stop.set()

    # -- queue ----------------------------------------------------------
    def enqueue(self, lecture_id: uuid.UUID, *, kind: str = "process") -> int:
        session = self.db.session()
        try:
            existing = session.execute(
                select(Job)
                .where(Job.lecture_id == lecture_id)
                .where(Job.status.in_(("queued", "running")))
                .order_by(Job.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                return existing.id
            lecture = session.get(Lecture, lecture_id)
            if lecture is None:
                raise ValueError(f"lecture {lecture_id} not found")
            lecture.status = "queued"
            lecture.stage = "queued"
            lecture.progress = 0.0
            lecture.error_message = None
            job = Job(lecture_id=lecture_id, kind=kind, status="queued")
            session.add(job)
            session.commit()
            return job.id
        finally:
            session.close()

    def recover(self) -> None:
        """Re-queue work interrupted by a restart (idempotent)."""
        session = self.db.session()
        try:
            session.execute(
                update(Job)
                .where(Job.status == "running")
                .values(status="queued", stage="queued", progress=0.0)
            )
            # collapse duplicates: keep only the newest queued job per lecture
            duplicates = session.execute(
                select(Job.lecture_id, Job.id).where(Job.status == "queued")
            ).all()
            seen: set[uuid.UUID] = set()
            for lecture_id, job_id in sorted(duplicates, key=lambda row: row[1], reverse=True):
                if lecture_id in seen:
                    session.execute(update(Job).where(Job.id == job_id).values(status="cancelled"))
                else:
                    seen.add(lecture_id)
            session.execute(
                update(Lecture)
                .where(Lecture.status.in_(("processing", "queued")))
                .values(status="queued", stage="queued", progress=0.0)
            )
            session.commit()
            if seen:
                log.info("recovered %d interrupted lecture(s)", len(seen))
        finally:
            session.close()

    def pending_count(self) -> int:
        session = self.db.session()
        try:
            rows = session.execute(
                select(Job.id).where(Job.status.in_(("queued", "running")))
            ).all()
            return len(rows)
        finally:
            session.close()

    # -- worker ---------------------------------------------------------
    def _claim(self) -> tuple[int, uuid.UUID] | None:
        session = self.db.session()
        try:
            job = session.execute(
                select(Job)
                .where(Job.status == "queued")
                .order_by(Job.created_at.asc(), Job.id.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            ).scalar_one_or_none()
            if job is None:
                session.rollback()
                return None
            job.status = "running"
            job.started_at = utcnow()
            job.attempts = (job.attempts or 0) + 1
            session.commit()
            return job.id, job.lecture_id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                claimed = self._claim()
            except Exception:
                log.exception("job claim failed")
                time.sleep(2.0)
                continue
            if claimed is None:
                self._stop.wait(1.2)
                continue

            job_id, lecture_id = claimed
            session = self.db.session()
            try:
                self.pipeline.process(session, lecture_id, job_id)
            except Exception:
                log.exception("pipeline crashed for lecture %s", lecture_id)
            finally:
                session.close()

            # A pipeline that died before writing a terminal state must not
            # leave the UI spinning forever.
            session = self.db.session()
            try:
                job = session.get(Job, job_id)
                lecture = session.get(Lecture, lecture_id)
                if lecture is not None and lecture.status in ("processing", "queued"):
                    lecture.status = "failed"
                    lecture.stage = "failed"
                    lecture.error_message = (
                        lecture.error_message or "Обработка прервана неожиданно. Попробуйте снова."
                    )
                if job is not None and job.status in ("running", "queued"):
                    job.status = "failed"
                    job.finished_at = utcnow()
                session.commit()
            except Exception:
                session.rollback()
            finally:
                session.close()
