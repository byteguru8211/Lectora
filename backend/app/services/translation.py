"""Segment-preserving RU/EN translation and optional spoken narration."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..errors import ApiError
from .llm_api import api_llm
from .llm_base import LlmUnavailable
from .media import discover_tools

log = logging.getLogger(__name__)


class TranslationService:
    _TTS_CHUNK_CHARS = 1600
    _TTS_ATTEMPTS = 3

    def translate(self, texts: list[str], source: str, target: str) -> list[str]:
        if not texts or source == target:
            return list(texts)
        result: list[str] = []
        for offset in range(0, len(texts), 24):
            batch = texts[offset:offset + 24]
            payload = {"segments": [{"id": offset + i, "text": text} for i, text in enumerate(batch)]}
            messages = [
                {"role": "system", "content": "You are a precise subtitle translator. Preserve meaning, terminology, numbers and formulas. Return only JSON: {\"segments\":[{\"id\":0,\"text\":\"...\"}]}. Never merge, omit or reorder segments."},
                {"role": "user", "content": f"Translate subtitles from {source} to {target}. Keep each line concise. Input: {payload}"},
            ]
            try:
                data = api_llm.chat_json(messages, max_tokens=4096, temperature=0.1)
            except LlmUnavailable as exc:
                log.warning("DeepSeek translation unavailable: %s", exc)
                raise ApiError(
                    "Перевод доступен только через работающий DeepSeek API",
                    503,
                    "translation_api_unavailable",
                ) from exc
            rows = data.get("segments", []) if isinstance(data, dict) else []
            mapped = {int(row.get("id")): str(row.get("text") or "").strip() for row in rows if isinstance(row, dict)}
            translated = [mapped.get(offset + i, "") for i in range(len(batch))]
            if any(not item for item in translated):
                raise ApiError("Не удалось получить полный перевод субтитров", 503, "translation_incomplete")
            result.extend(translated)
        return result

    def synthesize(self, text: str, target: Path, language: str) -> Path:
        try:
            import edge_tts
        except ImportError as exc:
            raise ApiError("Модуль озвучки edge-tts не установлен", 503, "tts_unavailable") from exc
        voice = "en-US-AriaNeural" if language == "en" else "ru-RU-SvetlanaNeural"
        target.parent.mkdir(parents=True, exist_ok=True)

        chunks = self._tts_chunks(text)
        if not chunks:
            raise ApiError("Нет текста для создания озвучки", 400, "tts_empty")

        # The cache survives a failed job. On the next attempt, chunks whose
        # text has not changed are reused instead of being requested again.
        parts_dir = target.parent / f".{target.stem}-parts"
        parts_dir.mkdir(parents=True, exist_ok=True)
        parts = [
            parts_dir / f"{index:04d}-{hashlib.sha256(chunk.encode('utf-8')).hexdigest()[:12]}.mp3"
            for index, chunk in enumerate(chunks)
        ]
        expected = {part.name for part in parts}
        for stale in parts_dir.glob("*.mp3"):
            if stale.name not in expected:
                stale.unlink(missing_ok=True)

        try:
            asyncio.run(self._synthesize_parts(edge_tts, chunks, parts, voice))
            self._concat_mp3(parts, target, parts_dir)
        except Exception as exc:
            log.exception(
                "TTS failed (voice=%s, chunks=%d, chars=%d): %s",
                voice,
                len(chunks),
                len(text),
                exc,
            )
            raise ApiError(
                "Не удалось создать озвучку перевода",
                503,
                "tts_failed",
                {"reason": str(exc)[:240]},
            ) from exc
        shutil.rmtree(parts_dir, ignore_errors=True)
        return target

    def _tts_chunks(self, text: str) -> list[str]:
        """Split narration at sentence/word boundaries for reliable requests."""
        clean = re.sub(r"\s+", " ", text).strip()
        if not clean:
            return []
        sentences = re.split(r"(?<=[.!?…])\s+", clean)
        units: list[str] = []
        for sentence in sentences:
            sentence = sentence.strip()
            while len(sentence) > self._TTS_CHUNK_CHARS:
                split_at = sentence.rfind(" ", 0, self._TTS_CHUNK_CHARS + 1)
                if split_at < self._TTS_CHUNK_CHARS // 2:
                    split_at = self._TTS_CHUNK_CHARS
                units.append(sentence[:split_at].strip())
                sentence = sentence[split_at:].strip()
            if sentence:
                units.append(sentence)

        chunks: list[str] = []
        current = ""
        for unit in units:
            candidate = f"{current} {unit}".strip()
            if current and len(candidate) > self._TTS_CHUNK_CHARS:
                chunks.append(current)
                current = unit
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    async def _synthesize_parts(self, edge_tts, chunks: list[str], parts: list[Path], voice: str) -> None:
        for index, (chunk, part) in enumerate(zip(chunks, parts, strict=True), start=1):
            if part.is_file() and part.stat().st_size > 512:
                log.info("TTS chunk %d/%d reused from cache", index, len(chunks))
                continue
            temp = part.with_suffix(".tmp.mp3")
            last_error: Exception | None = None
            for attempt in range(1, self._TTS_ATTEMPTS + 1):
                temp.unlink(missing_ok=True)
                try:
                    await edge_tts.Communicate(chunk, voice=voice).save(str(temp))
                    if not temp.is_file() or temp.stat().st_size <= 512:
                        raise RuntimeError("сервис озвучки вернул пустой аудиофайл")
                    os.replace(temp, part)
                    log.info("TTS chunk %d/%d ready (attempt %d)", index, len(chunks), attempt)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    temp.unlink(missing_ok=True)
                    log.warning(
                        "TTS chunk %d/%d attempt %d/%d failed: %s",
                        index,
                        len(chunks),
                        attempt,
                        self._TTS_ATTEMPTS,
                        exc,
                    )
                    if attempt < self._TTS_ATTEMPTS:
                        await asyncio.sleep(2 ** attempt)
            if last_error is not None:
                raise RuntimeError(
                    f"фрагмент {index}/{len(chunks)} не создан после {self._TTS_ATTEMPTS} попыток: {last_error}"
                ) from last_error

    def _concat_mp3(self, parts: list[Path], target: Path, parts_dir: Path) -> None:
        tools = discover_tools()
        if not tools.ffmpeg:
            raise RuntimeError("FFmpeg не найден для объединения фрагментов озвучки")
        manifest = parts_dir / "concat.txt"
        manifest.write_text(
            "\n".join(f"file '{part.resolve().as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" for part in parts),
            encoding="utf-8",
        )
        assembled = target.with_name(f".{target.stem}-assembling{target.suffix}")
        assembled.unlink(missing_ok=True)
        result = subprocess.run(
            [
                tools.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(manifest),
                "-c",
                "copy",
                str(assembled),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(60.0, min(600.0, len(parts) * 20.0)),
            creationflags=0x08000000 if os.name == "nt" else 0,
            check=False,
        )
        if result.returncode != 0 or not assembled.is_file() or assembled.stat().st_size <= 512:
            assembled.unlink(missing_ok=True)
            reason = (result.stderr or result.stdout or "неизвестная ошибка FFmpeg").strip()
            raise RuntimeError(f"не удалось объединить аудиофрагменты: {reason[:500]}")
        os.replace(assembled, target)


translation_service = TranslationService()
