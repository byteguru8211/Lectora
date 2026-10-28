"""Segment-preserving RU/EN translation and time-aligned spoken narration."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from ..errors import ApiError
from .llm_api import api_llm
from .llm_base import LlmUnavailable
from .media import discover_tools

log = logging.getLogger(__name__)

SAMPLE_RATE = 24_000


@dataclass(frozen=True)
class NarrationBlock:
    """A continuous piece of narration anchored to a video interval."""

    start: float
    end: float
    text: str


class TranslationService:
    _TTS_CHUNK_CHARS = 1600
    _TTS_ATTEMPTS = 3
    _TTS_CONCURRENCY = 4
    # Shorter pauses are read through: inserting sub-second silences makes the
    # narration sound chopped up without improving lip-sync.
    _BLOCK_GAP_MERGE = 0.6
    _BLOCK_MAX_SPAN = 30.0
    _BLOCK_MAX_CHARS = 1400
    # A phrase may finish up to this long after its last word: a natural tail
    # of the sentence, not narration over a channel card or a silent demo.
    _BLOCK_TAIL_ALLOWANCE = 0.8

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

    # -- narration ------------------------------------------------------
    def synthesize_timed(
        self,
        segments: Iterable[tuple[float, float, str]],
        duration: float,
        target: Path,
        language: str,
        on_progress: Callable[[float], None] | None = None,
    ) -> Path:
        """Build a narration track whose timeline matches the video exactly.

        Every block of translated text is synthesized separately and placed at
        its own start time; gaps in the original audio (channel cards, pauses,
        silent demonstrations) become real silences instead of being skipped.
        A block that runs longer than its slot is sped up, so the next block
        always starts on time.
        """
        try:
            import edge_tts
        except ImportError as exc:
            raise ApiError("Модуль озвучки edge-tts не установлен", 503, "tts_unavailable") from exc

        blocks = self._narration_blocks(segments)
        if not blocks:
            raise ApiError("Нет текста для создания озвучки", 400, "tts_empty")
        tools = discover_tools()
        if not tools.ffmpeg or not tools.ffprobe:
            raise ApiError(
                tools.issues[0] if tools.issues else "FFmpeg не найден для создания озвучки",
                503,
                "ffmpeg_missing",
            )

        voice = "en-US-AriaNeural" if language == "en" else "ru-RU-SvetlanaNeural"
        total = max(float(duration or 0.0), blocks[-1].end)
        target.parent.mkdir(parents=True, exist_ok=True)
        parts_dir = target.parent / f".{target.stem}-parts"
        work_dir = target.parent / f".{target.stem}-timed"
        shutil.rmtree(work_dir, ignore_errors=True)
        parts_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)

        try:
            chunks: list[str] = []
            block_parts: list[list[Path]] = []
            for block in blocks:
                block_chunks = self._tts_chunks(block.text)
                block_parts.append([self._part_path(parts_dir, chunk) for chunk in block_chunks])
                chunks.extend(block_chunks)
            self._drop_stale_parts(parts_dir, {part.name for part in self._unique(chunks, parts_dir)})

            unique_parts: list[Path] = []
            unique_chunks: list[str] = []
            seen: set[str] = set()
            for chunk in chunks:
                part = self._part_path(parts_dir, chunk)
                if part.name in seen:
                    continue
                seen.add(part.name)
                unique_chunks.append(chunk)
                unique_parts.append(part)
            asyncio.run(self._synthesize_parts(edge_tts, unique_chunks, unique_parts, voice))

            pieces: list[Path] = []
            cursor = 0.0
            for index, block in enumerate(blocks):
                is_last = index + 1 == len(blocks)
                next_start = total if is_last else blocks[index + 1].start
                gap = max(0.0, next_start - block.end)
                # Speech must not run through a long silence (channel card,
                # silent demonstration): only a short natural tail is allowed.
                slot_end = block.end + (0.0 if is_last else min(gap, self._BLOCK_TAIL_ALLOWANCE))
                slot = max(0.5, slot_end - block.start)
                if block.start - cursor > 0.02:
                    pieces.append(self._make_silence(work_dir, tools.ffmpeg, len(pieces), block.start - cursor))
                block_audio = work_dir / f"block-{index:04d}.mp3"
                self._concat_mp3(block_parts[index], block_audio, work_dir)
                spoken = self._probe_duration(tools.ffprobe, block_audio)
                pieces.append(
                    self._make_piece(work_dir, tools.ffmpeg, len(pieces), block_audio, spoken, slot)
                )
                cursor = block.start + slot
                if on_progress is not None:
                    on_progress((index + 1) / len(blocks))
                log.info(
                    "narration block %d/%d at %.1fs: slot %.2fs, speech %.2fs, speed %.2fx",
                    index + 1,
                    len(blocks),
                    block.start,
                    slot,
                    spoken,
                    max(1.0, spoken / slot),
                )
            if total - cursor > 0.02:
                pieces.append(self._make_silence(work_dir, tools.ffmpeg, len(pieces), total - cursor))

            merged = work_dir / "narration.wav"
            self._concat_wav(pieces, merged, work_dir)
            self._encode_mp3(tools.ffmpeg, merged, target)
        except Exception as exc:
            if isinstance(exc, ApiError):
                raise
            log.exception(
                "TTS failed (voice=%s, blocks=%d, duration=%.1fs): %s",
                voice,
                len(blocks),
                total,
                exc,
            )
            raise ApiError(
                "Не удалось создать озвучку перевода",
                503,
                "tts_failed",
                {"reason": str(exc)[:240]},
            ) from exc
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        shutil.rmtree(parts_dir, ignore_errors=True)
        return target

    def _narration_blocks(self, segments: Iterable[tuple[float, float, str]]) -> list[NarrationBlock]:
        blocks: list[NarrationBlock] = []
        for start, end, raw in segments:
            text = re.sub(r"\s+", " ", str(raw or "")).strip()
            if not text:
                continue
            start = max(0.0, float(start))
            end = max(start + 0.2, float(end))
            if blocks:
                last = blocks[-1]
                if (
                    start - last.end <= self._BLOCK_GAP_MERGE
                    and end - last.start <= self._BLOCK_MAX_SPAN
                    and len(last.text) + len(text) + 1 <= self._BLOCK_MAX_CHARS
                ):
                    blocks[-1] = NarrationBlock(last.start, end, f"{last.text} {text}")
                    continue
            blocks.append(NarrationBlock(start, end, text))
        return blocks

    @staticmethod
    def _part_path(parts_dir: Path, chunk: str) -> Path:
        digest = hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:16]
        return parts_dir / f"{digest}.mp3"

    @staticmethod
    def _unique(chunks: Sequence[str], parts_dir: Path) -> list[Path]:
        seen: set[str] = set()
        paths: list[Path] = []
        for chunk in chunks:
            path = TranslationService._part_path(parts_dir, chunk)
            if path.name not in seen:
                seen.add(path.name)
                paths.append(path)
        return paths

    def _drop_stale_parts(self, parts_dir: Path, keep: set[str]) -> None:
        for stale in parts_dir.glob("*.mp3"):
            if stale.name not in keep:
                stale.unlink(missing_ok=True)

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
        pending = [
            (index, chunk, part)
            for index, (chunk, part) in enumerate(zip(chunks, parts, strict=True), start=1)
            if not (part.is_file() and part.stat().st_size > 512)
        ]
        for index, _chunk, _part in pending:
            log.info("TTS chunk %d/%d reused from cache", index, len(chunks))
        if not pending:
            return

        gate = asyncio.Semaphore(self._TTS_CONCURRENCY)

        async def run(index: int, chunk: str, part: Path) -> None:
            async with gate:
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
                        return
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
                raise RuntimeError(
                    f"фрагмент {index}/{len(chunks)} не создан после {self._TTS_ATTEMPTS} попыток: {last_error}"
                ) from last_error

        await asyncio.gather(*(run(index, chunk, part) for index, chunk, part in pending))

    # -- ffmpeg helpers -------------------------------------------------
    @staticmethod
    def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=0x08000000 if os.name == "nt" else 0,
            check=False,
        )

    def _probe_duration(self, ffprobe: str, path: Path) -> float:
        result = self._run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            timeout=60,
        )
        try:
            return float((result.stdout or "").strip())
        except ValueError:
            raise RuntimeError(f"не удалось определить длительность фрагмента {path.name}") from None

    @staticmethod
    def _tempo_filters(ratio: float) -> list[str]:
        filters: list[str] = []
        factor = max(1.0, ratio)
        while factor > 2.0:
            filters.append("atempo=2.0")
            factor /= 2.0
        if factor > 1.01:
            filters.append(f"atempo={factor:.4f}")
        return filters

    def _make_piece(
        self,
        work_dir: Path,
        ffmpeg: str,
        index: int,
        source: Path,
        spoken: float,
        slot: float,
    ) -> Path:
        path = work_dir / f"piece-{index:04d}.wav"
        filters = self._tempo_filters(spoken / slot) + [f"aresample={SAMPLE_RATE}", "apad"]
        result = self._run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source),
                "-af",
                ",".join(filters),
                "-t",
                f"{slot:.4f}",
                "-ac",
                "1",
                "-ar",
                str(SAMPLE_RATE),
                "-c:a",
                "pcm_s16le",
                str(path),
            ],
            timeout=max(30.0, min(120.0, slot * 4)),
        )
        if result.returncode != 0 or not path.is_file():
            reason = (result.stderr or result.stdout or "неизвестная ошибка FFmpeg").strip()
            raise RuntimeError(f"не удалось выровнять фрагмент озвучки: {reason[:300]}")
        return path

    def _make_silence(self, work_dir: Path, ffmpeg: str, index: int, seconds: float) -> Path:
        path = work_dir / f"piece-{index:04d}.wav"
        result = self._run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r={SAMPLE_RATE}:cl=mono",
                "-t",
                f"{seconds:.4f}",
                "-c:a",
                "pcm_s16le",
                str(path),
            ],
            timeout=60,
        )
        if result.returncode != 0 or not path.is_file():
            raise RuntimeError("не удалось создать паузу в озвучке")
        return path

    def _concat_mp3(self, parts: list[Path], target: Path, work_dir: Path) -> None:
        ffmpeg = discover_tools().ffmpeg
        if not ffmpeg:
            raise RuntimeError("FFmpeg не найден для объединения фрагментов озвучки")
        manifest = work_dir / f"{target.stem}.txt"
        manifest.write_text(
            "\n".join(f"file '{part.resolve().as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" for part in parts),
            encoding="utf-8",
        )
        result = self._run(
            [
                ffmpeg,
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
                str(target),
            ],
            timeout=max(60.0, min(600.0, len(parts) * 20.0)),
        )
        if result.returncode != 0 or not target.is_file() or target.stat().st_size <= 512:
            target.unlink(missing_ok=True)
            reason = (result.stderr or result.stdout or "неизвестная ошибка FFmpeg").strip()
            raise RuntimeError(f"не удалось объединить аудиофрагменты: {reason[:500]}")

    def _concat_wav(self, pieces: list[Path], target: Path, work_dir: Path) -> None:
        ffmpeg = discover_tools().ffmpeg
        manifest = work_dir / "pieces.txt"
        manifest.write_text(
            "\n".join(f"file '{piece.resolve().as_posix()}'" for piece in pieces),
            encoding="utf-8",
        )
        result = self._run(
            [
                ffmpeg,
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
                str(target),
            ],
            timeout=max(60.0, min(600.0, len(pieces) * 20.0)),
        )
        if result.returncode != 0 or not target.is_file() or target.stat().st_size <= 512:
            target.unlink(missing_ok=True)
            reason = (result.stderr or result.stdout or "неизвестная ошибка FFmpeg").strip()
            raise RuntimeError(f"не удалось собрать дорожку озвучки: {reason[:500]}")

    def _encode_mp3(self, ffmpeg: str, source: Path, target: Path) -> None:
        assembled = target.with_name(f".{target.stem}-assembling{target.suffix}")
        assembled.unlink(missing_ok=True)
        result = self._run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source),
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                "-ac",
                "1",
                "-ar",
                str(SAMPLE_RATE),
                str(assembled),
            ],
            timeout=600,
        )
        if result.returncode != 0 or not assembled.is_file() or assembled.stat().st_size <= 512:
            assembled.unlink(missing_ok=True)
            reason = (result.stderr or result.stdout or "неизвестная ошибка FFmpeg").strip()
            raise RuntimeError(f"не удалось закодировать озвучку: {reason[:500]}")
        os.replace(assembled, target)


translation_service = TranslationService()
