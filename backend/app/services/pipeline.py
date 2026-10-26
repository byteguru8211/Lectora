"""The processing pipeline: video → audio → text → chunks → notes.

Design notes
------------
* Runs in a worker thread with its own SQLAlchemy session; the HTTP request
  that uploaded the file returns immediately.
* Every stage writes ``stage``/``progress`` to both the lecture and the job, so
  the UI (SSE) and crash recovery see the same truth.
* Re-processing is idempotent: old segments/chunks/sections are replaced only
  after the new transcript is ready.
* Any failure leaves the lecture in ``failed`` with a human-readable reason,
  never in a half-processed state.
"""

from __future__ import annotations

import logging
import mimetypes
import time
import uuid
from pathlib import Path

from sqlalchemy import delete

from ..config import Config
from ..errors import ApiError
from ..models import (
    Chunk,
    Job,
    Lecture,
    QaMessage,
    Section,
    TranscriptSegment,
    utcnow,
)
from ..utils.text import normalize_space
from ..utils.timefmt import format_timestamp
from .asr import AsrService, Segment
from .chunker import build_chunks
from .embeddings import embeddings
from .llm import llm
from .media import MediaService
from .search import search_service
from .storage import Storage
from .summarizer import summarizer

log = logging.getLogger(__name__)

STAGE_LABELS = {
    "queued": "В очереди",
    "download": "Загрузка видео по ссылке",
    "probe": "Анализ файла",
    "transcode": "Подготовка видео",
    "audio": "Извлечение звука",
    "model": "Загрузка модели распознавания",
    "transcribe": "Распознавание речи",
    "punctuate": "Оформление текста",
    "embed": "Семантический индекс",
    "notes": "Конспект и структура",
    "finalize": "Завершение",
    "done": "Готово",
    "failed": "Ошибка",
}


class Progress:
    """Throttled progress writer shared by all pipeline stages."""

    def __init__(self, session, lecture: Lecture, job: Job | None) -> None:
        self.session = session
        self.lecture = lecture
        self.job = job
        self._last_percent = -1.0
        self._last_at = 0.0

    def update(self, stage: str, percent: float, *, force: bool = False) -> None:
        percent = max(0.0, min(100.0, percent))
        now = time.monotonic()
        if not force and percent - self._last_percent < 1.2 and now - self._last_at < 1.0:
            return
        self.lecture.stage = stage
        self.lecture.progress = round(percent, 1)
        if self.job is not None:
            self.job.stage = stage
            self.job.progress = round(percent, 1)
        self.session.commit()
        self._last_percent = percent
        self._last_at = now

    def fail(self, message: str) -> None:
        self.lecture.status = "failed"
        self.lecture.stage = "failed"
        self.lecture.error_message = message[:2000]
        self.lecture.progress = 0.0
        if self.job is not None:
            self.job.status = "failed"
            self.job.stage = "failed"
            self.job.error_message = message[:2000]
            self.job.finished_at = utcnow()
        self.session.commit()


class Pipeline:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self.asr = AsrService()

    # -- entry point ----------------------------------------------------
    def process(self, session, lecture_id: uuid.UUID, job_id: int | None = None) -> None:
        started = time.perf_counter()
        lecture = session.get(Lecture, lecture_id)
        if lecture is None:
            log.warning("pipeline: lecture %s disappeared", lecture_id)
            return
        job = session.get(Job, job_id) if job_id else None
        progress = Progress(session, lecture, job)
        lecture.status = "processing"
        lecture.error_message = None
        progress.update("probe", 2.0, force=True)
        log.info("pipeline start %s (%s)", lecture.id, lecture.title)

        try:
            media = MediaService()
            media.require()
            media_dir = Path(self.storage.lecture_dir(lecture.storage_key))

            # -- URL import: the download is part of the pipeline ---------
            existing = self.storage.path_for(lecture.video_path)
            if lecture.source_type == "url" and (existing is None or not Path(existing).exists()):
                if not lecture.source_url:
                    raise ApiError("У лекции нет ссылки для импорта", 400, "source_url_missing")
                progress.update("download", 1.0, force=True)
                downloaded = media.download_url(lecture.source_url, media_dir)
                target = media_dir / f"original{downloaded.suffix.lower() or '.mp4'}"
                if downloaded != target:
                    downloaded.replace(target)
                lecture.video_path = self.storage.relative(target)
                lecture.original_filename = target.name[:255]
                session.commit()

            source = self.storage.path_for(lecture.video_path)
            if source is None or not Path(source).exists():
                raise ApiError("Файл лекции не найден в хранилище", 500, "file_missing")

            info = media.probe(Path(source))
            duration = float(info.duration or 0.0)

            progress.update("transcode", 4.0, force=True)
            playable, info = media.ensure_playable(Path(source), media_dir)
            if playable != Path(source):
                lecture.video_path = self.storage.relative(playable)
                Path(source).unlink(missing_ok=True)
                duration = float(info.duration or duration)

            if not info.has_audio:
                raise ApiError(
                    "В этом видео нет звуковой дорожки — распознавать нечего.",
                    422,
                    "no_audio_track",
                )
            duration = duration or 0.0
            lecture.duration_sec = round(duration, 2)
            lecture.width = info.width
            lecture.height = info.height
            lecture.mime_type = (
                mimetypes.guess_type(str(playable))[0]
                or ("video/mp4" if info.has_video else "audio/mpeg")
            )

            progress.update("audio", 6.0, force=True)
            thumb_at = max(0.5, min(duration * 0.08, 30.0)) if duration else 0.0
            thumb = media.thumbnail(playable, media_dir / "thumb.jpg", thumb_at)
            if thumb:
                lecture.thumbnail_path = self.storage.relative(thumb)

            audio_path = media.extract_audio(
                playable,
                media_dir / "audio.wav",
                on_progress=lambda seconds: progress.update(
                    "audio",
                    6.0 + 12.0 * (seconds / duration if duration else 0.0),
                ),
            )
            lecture.audio_path = self.storage.relative(audio_path)

            progress.update("transcribe", 18.0, force=True)
            if not self.asr.is_loaded(lecture.asr_profile):
                progress.update("model", 18.5, force=True)
            eta = self.asr.eta_seconds(duration, lecture.asr_profile)
            log.info("ASR %s, %.0fs audio, ~%ss ETA", lecture.asr_profile, duration, eta)
            transcription = self.asr.transcribe(
                audio_path,
                profile=lecture.asr_profile,
                on_progress=lambda ratio: progress.update("transcribe", 18.0 + 50.0 * ratio),
                duration_hint=duration,
            )
            duration = duration or transcription.duration_sec

            segments: list[Segment] = self._punctuate(transcription.segments)
            if not segments:
                raise ApiError("Не удалось разбить распознанный текст", 422, "empty_transcript")

            progress.update("embed", 70.0, force=True)
            chunks = build_chunks(
                segments,
                max_chars=Config.CHUNK_MAX_CHARS,
                max_sec=Config.CHUNK_MAX_SEC,
                overlap_segments=Config.CHUNK_OVERLAP_SEGMENTS,
            )
            if not chunks:
                raise ApiError("Не удалось собрать семантические фрагменты", 422, "no_chunks")

            vectors = embeddings.encode_documents(
                [chunk.text for chunk in chunks],
                on_progress=lambda ratio: progress.update("embed", 70.0 + 12.0 * ratio),
            )

            # -- persist transcript & index ----------------------------
            session.execute(delete(Chunk).where(Chunk.lecture_id == lecture.id))
            session.execute(
                delete(TranscriptSegment).where(TranscriptSegment.lecture_id == lecture.id)
            )
            session.execute(delete(Section).where(Section.lecture_id == lecture.id))
            session.execute(delete(QaMessage).where(QaMessage.lecture_id == lecture.id))
            session.flush()

            segment_rows = [
                {
                    "lecture_id": lecture.id,
                    "idx": index,
                    "start_sec": segment.start_sec,
                    "end_sec": segment.end_sec,
                    "text": normalize_space(segment.text),
                    "words": [word.as_dict() for word in segment.words],
                }
                for index, segment in enumerate(segments)
            ]
            session.bulk_insert_mappings(TranscriptSegment, segment_rows)

            chunk_rows = [
                {
                    "lecture_id": lecture.id,
                    "idx": index,
                    "start_sec": chunk.start_sec,
                    "end_sec": chunk.end_sec,
                    "text": chunk.text,
                    "token_count": chunk.token_count,
                    "embedding": embeddings.to_bytes(vectors[index]),
                    "dim": int(vectors.shape[1]),
                }
                for index, chunk in enumerate(chunks)
            ]
            session.bulk_insert_mappings(Chunk, chunk_rows)

            lecture.segment_count = len(segment_rows)
            lecture.chunk_count = len(chunk_rows)
            lecture.word_count = transcription.word_count
            lecture.transcript_chars = sum(len(row["text"]) for row in segment_rows)
            lecture.duration_sec = round(duration, 2)
            session.commit()

            # -- notes -------------------------------------------------
            progress.update("notes", 84.0, force=True)
            notes = summarizer.build(
                title="" if lecture.title_auto else lecture.title,
                segments=segments,
                duration_sec=duration,
            )
            for index, draft in enumerate(notes.sections):
                session.add(
                    Section(
                        lecture_id=lecture.id,
                        idx=index,
                        title=draft.title[:300],
                        summary=draft.summary or None,
                        start_sec=draft.start_sec,
                        end_sec=draft.end_sec,
                        key_points=draft.key_points,
                    )
                )
            lecture.summary = notes.summary
            lecture.keywords = notes.keywords
            lecture.llm_model = notes.model if notes.llm_used else None
            if lecture.title_auto and notes.title:
                generated = notes.title.strip()
                if len(generated) >= 3 and generated.lower() != lecture.title.strip().lower():
                    lecture.title = generated[:300]
                    log.info("generated title: %s", lecture.title)
            session.commit()

            progress.update("finalize", 98.0, force=True)
            lecture.status = "ready"
            lecture.stage = "done"
            lecture.progress = 100.0
            lecture.processed_at = utcnow()
            lecture.processing_ms = int((time.perf_counter() - started) * 1000)
            if job is not None:
                job.status = "done"
                job.stage = "done"
                job.progress = 100.0
                job.finished_at = utcnow()
            session.commit()
            search_service.invalidate(lecture.id)
            log.info(
                "pipeline done %s in %.1fs (%d segments, %d chunks, llm=%s)",
                lecture.id,
                (time.perf_counter() - started),
                lecture.segment_count,
                lecture.chunk_count,
                lecture.llm_model or "extractive",
            )
        except ApiError as exc:
            log.warning("pipeline failed %s: %s", lecture.id, exc.message)
            progress.fail(exc.message)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("pipeline crashed %s", lecture.id)
            progress.fail(f"Обработка прервана: {exc}")

    # -- optional LLM punctuation --------------------------------------
    def _punctuate(self, segments: list[Segment]) -> list[Segment]:
        mode = Config.PUNCTUATION_MODE
        if mode != "llm" or not Config.LLM_ENABLED or not llm.available:
            return segments
        batch_size = 40
        total = len(segments)
        polished: list[Segment] = []
        for start in range(0, total, batch_size):
            window = segments[start : start + batch_size]
            numbered = "\n".join(
                f"{index + 1}. {segment.text}" for index, segment in enumerate(window)
            )
            try:
                data = llm.chat_json(
                    [
                        {
                            "role": "system",
                            "content": (
                                "Ты редактор расшифровок лекций. Восстанови пунктуацию, "
                                "заглавные буквы и разбей на предложения, не меняя слова и "
                                "порядок. Верни JSON {\"segments\": [\"...\", \"...\"]} — "
                                "ровно столько же элементов, сколько строк на входе."
                            ),
                        },
                        {"role": "user", "content": numbered},
                    ],
                    max_tokens=1600,
                    temperature=0.0,
                )
            except Exception:
                log.warning("punctuation: LLM failed, keeping rule-based text")
                return segments
            items = data.get("segments") if isinstance(data, dict) else None
            if not isinstance(items, list) or len(items) != len(window):
                log.info("punctuation: unexpected batch shape, keeping rules")
                polished.extend(window)
                continue
            for segment, text in zip(window, items):
                cleaned = normalize_space(str(text))
                polished.append(
                    Segment(
                        start_sec=segment.start_sec,
                        end_sec=segment.end_sec,
                        text=cleaned or segment.text,
                        words=segment.words,
                    )
                )
        return polished

    # -- helpers --------------------------------------------------------
    @staticmethod
    def eta_text(duration_sec: float, profile: str) -> str:
        rate = 0.11 if profile == "fast" else 0.35
        seconds = int(duration_sec * rate) + 30
        return format_timestamp(seconds)


pipeline: Pipeline | None = None


def init_pipeline(storage: Storage) -> Pipeline:
    global pipeline
    pipeline = Pipeline(storage)
    return pipeline


def get_pipeline(storage: Storage) -> Pipeline:
    if pipeline is None:
        return init_pipeline(storage)
    return pipeline
