"""Whisper audio preparation and CPU fallback."""

from __future__ import annotations

import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.errors import ApiError
from app.services.whisper_asr import WhisperAsrService


def _write_wav(path: Path, *, channels: int = 1, rate: int = 16000, frames: int = 1600) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        samples = np.zeros(frames * channels, dtype=np.int16)
        samples[::2] = 16384
        handle.writeframes(samples.tobytes())
    return path


def test_read_wav_returns_normalized_float32(tmp_path):
    audio = WhisperAsrService._read_wav(_write_wav(tmp_path / "a.wav"))
    assert audio.dtype == np.float32
    assert audio.shape == (1600,)
    assert float(audio.max()) == pytest.approx(0.5, abs=1e-3)


def test_read_wav_rejects_stereo(tmp_path):
    with pytest.raises(ApiError) as info:
        WhisperAsrService._read_wav(_write_wav(tmp_path / "b.wav", channels=2))
    assert info.value.code == "whisper_audio_failed"


def test_transcribe_uses_cpu_when_cuda_unavailable(tmp_path, monkeypatch):
    service = WhisperAsrService()
    source = _write_wav(tmp_path / "c.wav")
    used: dict = {}

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            used["ndarray"] = isinstance(audio, np.ndarray)
            segment = SimpleNamespace(
                start=0.0,
                end=1.0,
                text=" привет",
                words=[SimpleNamespace(word="привет", start=0.0, end=1.0, probability=0.9)],
            )
            return [segment], SimpleNamespace(duration=1.0)

    def fake_load(device: str):
        used["device"] = device
        return FakeModel()

    monkeypatch.setattr(service, "_cuda_available", lambda: False)
    monkeypatch.setattr(service, "_load", fake_load)

    result = service.transcribe(source, use_gpu=True)
    assert used == {"device": "cpu", "ndarray": True}
    assert result.word_count == 1
    assert result.segments[0].text == "привет"
