"""Speech-to-text with Vosk (fully offline)."""

from __future__ import annotations

import json
import logging
import math
import threading
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..config import Config
from ..errors import ApiError
from ..utils.text import restore_punctuation

log = logging.getLogger(__name__)

ProgressCb = Callable[[float], None]


@dataclass
class Word:
    word: str
    start: float
    end: float
    conf: float = 1.0

    def as_dict(self) -> dict:
        return {
            "w": self.word,
            "s": round(self.start, 2),
            "e": round(self.end, 2),
        }


@dataclass
class Segment:
    start_sec: float
    end_sec: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcription:
    segments: list[Segment]
    word_count: int
    duration_sec: float

    @property
    def text(self) -> str:
        return " ".join(segment.text for segment in self.segments)

    @property
    def chars(self) -> int:
        return len(self.text)


class AsrService:
    """Loads a Vosk model once and keeps it warm for the worker thread."""

    def __init__(self) -> None:
        self._model = None
        self._model_profile: str | None = None
        self._lock = threading.Lock()

    # -- models --------------------------------------------------------
    def model_path(self, profile: str) -> Path:
        if profile == "fast":
            return Path(Config.ASR_MODEL_FAST)
        return Path(Config.ASR_MODEL_ACCURATE)

    def available_profiles(self) -> dict[str, bool]:
        return {
            "accurate": self.model_path("accurate").is_dir(),
            "fast": self.model_path("fast").is_dir(),
        }

    def _load_model(self, profile: str):
        import vosk

        path = self.model_path(profile)
        if not path.is_dir():
            raise ApiError(
                f"Модель Vosk не найдена: {path}. Скачайте её и распакуйте в models/vosk.",
                503,
                "asr_model_missing",
                {"profile": profile, "path": str(path)},
            )
        if self._model is not None and self._model_profile == profile:
            return self._model
        with self._lock:
            if self._model is not None and self._model_profile == profile:
                return self._model
            log.info("loading Vosk model %s (%s)", profile, path)
            vosk.SetLogLevel(-1)
            self._model = vosk.Model(str(path))
            self._model_profile = profile
            log.info("Vosk model %s loaded", profile)
            return self._model

    def warm_up(self, profile: str | None = None) -> bool:
        try:
            self._load_model(profile or Config.ASR_DEFAULT_PROFILE)
            return True
        except Exception:  # pragma: no cover - optional warmup
            log.exception("Vosk warm-up failed")
            return False

    def is_loaded(self, profile: str) -> bool:
        return self._model is not None and self._model_profile == profile

    # -- transcription --------------------------------------------------
    def transcribe(
        self,
        wav_path: Path,
        *,
        profile: str = "accurate",
        on_progress: ProgressCb | None = None,
        duration_hint: float | None = None,
    ) -> Transcription:
        import vosk

        model = self._load_model(profile)
        wav_path = Path(wav_path)
        if not wav_path.is_file():
            raise ApiError("Аудиофайл не найден", 500, "audio_missing")

        with wave.open(str(wav_path), "rb") as handle:
            sample_rate = handle.getframerate()
            total_frames = handle.getnframes()
            duration = total_frames / float(sample_rate or 16000) if sample_rate else 0.0
            if sample_rate != Config.ASR_SAMPLE_RATE:
                raise ApiError(
                    f"Ожидался WAV 16 кГц, получен {sample_rate} Гц",
                    500,
                    "bad_audio_format",
                )
            recognizer = vosk.KaldiRecognizer(model, sample_rate)
            recognizer.SetWords(True)

            words: list[Word] = []
            processed = 0.0
            chunk_bytes = int(sample_rate * 2 * 0.5)  # 0.5 s of 16-bit mono

            while True:
                data = handle.readframes(chunk_bytes // 2)
                if not data:
                    break
                if recognizer.AcceptWaveform(data):
                    words.extend(self._parse_words(recognizer.Result()))
                processed += (len(data) / 2) / float(sample_rate)
                if on_progress:
                    on_progress(min(1.0, processed / duration) if duration else 0.0)

            words.extend(self._parse_words(recognizer.FinalResult()))

        if not words:
            raise ApiError(
                "В записи не распознана речь. Проверьте, что в видео есть звук.",
                422,
                "no_speech_detected",
            )

        segments = self._build_segments(words)
        log.info(
            "transcribed %s: %d words, %d segments, %.1f s",
            wav_path.name, len(words), len(segments), duration,
        )
        return Transcription(
            segments=segments,
            word_count=len(words),
            duration_sec=duration or (duration_hint or 0.0),
        )

    @staticmethod
    def _parse_words(payload: str) -> list[Word]:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []
        result = data.get("result") or []
        words: list[Word] = []
        for item in result:
            token = str(item.get("word") or "").strip()
            if not token:
                continue
            words.append(
                Word(
                    word=token,
                    start=float(item.get("start") or 0.0),
                    end=float(item.get("end") or 0.0),
                    conf=float(item.get("conf") or 1.0),
                )
            )
        return words

    def _build_segments(self, words: list[Word]) -> list[Segment]:
        segments: list[Segment] = []
        bucket: list[Word] = []

        def flush() -> None:
            if not bucket:
                return
            raw = " ".join(word.word for word in bucket)
            text = restore_punctuation(raw, end="." if len(bucket) > 3 else ",")
            segments.append(
                Segment(
                    start_sec=round(bucket[0].start, 2),
                    end_sec=round(max(bucket[-1].end, bucket[0].start + 0.2), 2),
                    text=text,
                    words=list(bucket),
                )
            )
            bucket.clear()

        for word in words:
            if bucket:
                gap = word.start - bucket[-1].end
                too_wide = (word.end - bucket[0].start) > Config.SEGMENT_MAX_SEC
                too_long = len(bucket) >= 18
                if gap > Config.SEGMENT_PAUSE_SEC or too_wide or too_long:
                    flush()
            bucket.append(word)
        flush()
        return segments

    def estimate_rtf(self, profile: str) -> float:
        """Rough real-time factor used for ETA in the UI."""
        return 0.11 if profile == "fast" else 0.35

    def eta_seconds(self, duration_sec: float, profile: str) -> int:
        return int(math.ceil(duration_sec * self.estimate_rtf(profile)))
