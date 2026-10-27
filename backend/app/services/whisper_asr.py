"""GPU/CPU speech recognition through faster-whisper (CTranslate2)."""

from __future__ import annotations

import gc
import logging
import wave
from pathlib import Path

import numpy as np

from ..config import Config
from ..errors import ApiError
from .asr import ProgressCb, Segment, Transcription, Word

log = logging.getLogger(__name__)


class WhisperAsrService:
    def __init__(self) -> None:
        self._model = None
        self._device: str | None = None

    def _load(self, device: str):
        if self._model is not None and self._device == device:
            return self._model
        self.unload()
        try:
            from faster_whisper import WhisperModel

            compute_type = Config.WHISPER_COMPUTE_TYPE if device == "cuda" else "int8"
            Path(Config.WHISPER_MODEL_DIR).mkdir(parents=True, exist_ok=True)
            log.info("loading faster-whisper %s on %s (%s)", Config.WHISPER_MODEL, device, compute_type)
            self._model = WhisperModel(
                Config.WHISPER_MODEL,
                device=device,
                compute_type=compute_type,
                download_root=str(Config.WHISPER_MODEL_DIR),
            )
            self._device = device
            return self._model
        except Exception as exc:
            self.unload()
            raise ApiError(
                "Whisper не удалось запустить на видеокарте; используем резервный Vosk.",
                503,
                "whisper_unavailable",
                {"reason": str(exc)[:300]},
            ) from exc

    def transcribe(
        self,
        wav_path: Path,
        *,
        use_gpu: bool = True,
        on_progress: ProgressCb | None = None,
        duration_hint: float | None = None,
        language: str = "ru",
    ) -> Transcription:
        if use_gpu and not self._cuda_available():
            log.info("CUDA unavailable for Whisper; using CPU")
            use_gpu = False
        device = "cuda" if use_gpu else "cpu"
        model = self._load(device)
        # Decode the 16 kHz mono PCM ourselves: newer PyAV releases dropped the
        # metadata_errors argument that faster-whisper passes to av.open.
        raw_segments, info = model.transcribe(
            self._read_wav(wav_path),
            language=language,
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=True,
        )
        segments: list[Segment] = []
        word_count = 0
        duration = float(duration_hint or getattr(info, "duration", 0.0) or 0.0)
        for item in raw_segments:
            words = [
                Word(
                    word=str(word.word).strip(),
                    start=float(word.start or item.start),
                    end=float(word.end or item.end),
                    conf=float(word.probability or 1.0),
                )
                for word in (item.words or [])
                if str(word.word).strip()
            ]
            text = str(item.text or "").strip()
            if text:
                segments.append(Segment(float(item.start), float(item.end), text, words))
                word_count += len(words) or len(text.split())
            if on_progress and duration:
                on_progress(min(1.0, float(item.end) / duration))
        if not segments:
            raise ApiError("Whisper не распознал речь в записи", 422, "no_speech_detected")
        log.info("faster-whisper transcribed %s: %d words, %d segments", Path(wav_path).name, word_count, len(segments))
        return Transcription(segments=segments, word_count=word_count, duration_sec=duration)

    @staticmethod
    def _read_wav(path: Path) -> np.ndarray:
        try:
            with wave.open(str(path), "rb") as handle:
                if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
                    raise ValueError("expected mono 16-bit PCM")
                if handle.getframerate() != Config.ASR_SAMPLE_RATE:
                    raise ValueError(f"expected {Config.ASR_SAMPLE_RATE} Hz")
                frames = handle.readframes(handle.getnframes())
        except (OSError, EOFError, ValueError) as exc:
            raise ApiError(
                "Не удалось прочитать аудио для Whisper",
                422,
                "whisper_audio_failed",
                {"reason": str(exc)[:200]},
            ) from exc
        return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    @staticmethod
    def _cuda_available() -> bool:
        try:
            import torch

            return bool(torch.cuda.is_available())
        except Exception:
            return False

    def unload(self) -> None:
        self._model = None
        self._device = None
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
