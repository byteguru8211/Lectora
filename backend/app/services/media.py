"""ffmpeg/ffprobe integration: probing, audio extraction, thumbnails."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..errors import ApiError

log = logging.getLogger(__name__)

_WEB_VIDEO_CODECS = {"h264", "vp8", "vp9", "av1"}
_WEB_CONTAINERS = {".mp4", ".webm", ".m4v", ".mov"}


@dataclass
class MediaInfo:
    duration: float = 0.0
    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    container: str = ""
    has_video: bool = False
    has_audio: bool = False
    bitrate: int | None = None

    @property
    def resolution(self) -> str | None:
        if self.width and self.height:
            return f"{self.width}×{self.height}"
        return None

    def as_dict(self) -> dict:
        return {
            "duration_sec": round(self.duration, 2),
            "width": self.width,
            "height": self.height,
            "resolution": self.resolution,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "container": self.container,
            "has_video": self.has_video,
            "has_audio": self.has_audio,
        }


@dataclass
class Tools:
    ffmpeg: str
    ffprobe: str
    ytdlp: str | None = None
    issues: list[str] = field(default_factory=list)


_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _run(args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_NO_WINDOW,
        check=False,
    )


def _first_existing(*candidates: str | Path | None) -> str | None:
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return str(path)
    return None


def discover_tools() -> Tools:
    """Find bundled tools first, then fall back to PATH."""
    tools_dir = Path(Config.TOOLS_DIR)
    ffmpeg = _first_existing(
        Config.FFMPEG_BIN or None,
        tools_dir / "ffmpeg" / "bin" / "ffmpeg.exe",
        tools_dir / "ffmpeg" / "ffmpeg.exe",
        shutil.which("ffmpeg"),
    )
    ffprobe = _first_existing(
        Config.FFPROBE_BIN or None,
        tools_dir / "ffmpeg" / "bin" / "ffprobe.exe",
        tools_dir / "ffmpeg" / "ffprobe.exe",
        shutil.which("ffprobe"),
    )
    ytdlp = _first_existing(
        Config.YTDLP_BIN or None,
        tools_dir / "yt-dlp" / "yt-dlp.exe",
        shutil.which("yt-dlp"),
    )
    issues: list[str] = []
    if not ffmpeg:
        issues.append(
            "ffmpeg не найден. Положите ffmpeg.exe и ffprobe.exe в tools/ffmpeg/bin "
            "или установите ffmpeg и добавьте его в PATH."
        )
    if not ffprobe:
        issues.append("ffprobe не найден (нужен для определения длительности видео).")
    return Tools(ffmpeg=ffmpeg or "", ffprobe=ffprobe or "", ytdlp=ytdlp, issues=issues)


class MediaService:
    def __init__(self) -> None:
        self.tools = discover_tools()

    # -- public API ----------------------------------------------------
    @property
    def available(self) -> bool:
        return bool(self.tools.ffmpeg and self.tools.ffprobe)

    def require(self) -> None:
        if not self.available:
            raise ApiError(
                self.tools.issues[0] if self.tools.issues else "ffmpeg недоступен",
                503,
                "ffmpeg_missing",
            )

    def probe(self, path: Path) -> MediaInfo:
        self.require()
        proc = _run(
            [
                self.tools.ffprobe,
                "-v", "error",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            timeout=120,
        )
        if proc.returncode != 0:
            raise ApiError(
                "Не удалось прочитать видеофайл. Проверьте, что файл не повреждён.",
                422,
                "probe_failed",
                {"stderr": (proc.stderr or "")[-400:]},
            )
        data = json.loads(proc.stdout or "{}")
        fmt = data.get("format") or {}
        streams = data.get("streams") or []
        info = MediaInfo()
        info.container = str(fmt.get("format_name") or "")
        try:
            info.duration = float(fmt.get("duration") or 0.0)
        except (TypeError, ValueError):
            info.duration = 0.0
        try:
            info.bitrate = int(fmt.get("bit_rate") or 0) or None
        except (TypeError, ValueError):
            info.bitrate = None

        for stream in streams:
            if stream.get("codec_type") == "video" and not info.has_video:
                info.has_video = True
                info.video_codec = stream.get("codec_name")
                info.width = stream.get("width")
                info.height = stream.get("height")
                if not info.duration and stream.get("duration"):
                    info.duration = float(stream["duration"])
            elif stream.get("codec_type") == "audio" and not info.has_audio:
                info.has_audio = True
                info.audio_codec = stream.get("codec_name")
        return info

    def extract_audio(
        self,
        source: Path,
        target: Path,
        *,
        on_progress: callable | None = None,
    ) -> Path:
        """Decode any input into 16 kHz mono PCM — exactly what Vosk wants."""
        self.require()
        target.parent.mkdir(parents=True, exist_ok=True)
        args = [
            self.tools.ffmpeg,
            "-hide_banner", "-nostdin", "-y",
            "-i", str(source),
            "-vn",
            "-ac", "1",
            "-ar", str(Config.ASR_SAMPLE_RATE),
            "-acodec", "pcm_s16le",
            "-progress", "pipe:1",
            "-loglevel", "error",
            str(target),
        ]
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            if on_progress and line.startswith("out_time_ms="):
                raw = line.split("=", 1)[1].strip()
                if raw.isdigit():
                    on_progress(int(raw) / 1_000_000)
        _, stderr = proc.communicate(timeout=3600)
        if proc.returncode != 0 or not target.exists():
            raise ApiError(
                "Не удалось извлечь аудиодорожку из видео.",
                422,
                "audio_extraction_failed",
                {"stderr": (stderr or "")[-400:]},
            )
        return target

    def thumbnail(self, source: Path, target: Path, at_sec: float) -> Path | None:
        self.require()
        target.parent.mkdir(parents=True, exist_ok=True)
        for moment in (at_sec, 1.0, 0.0):
            proc = _run(
                [
                    self.tools.ffmpeg,
                    "-hide_banner", "-nostdin", "-y",
                    "-ss", f"{max(0.0, moment):.3f}",
                    "-i", str(source),
                    "-frames:v", "1",
                    "-vf", "scale=720:-2",
                    "-q:v", "3",
                    str(target),
                ],
                timeout=120,
            )
            if proc.returncode == 0 and target.exists() and target.stat().st_size > 0:
                return target
        log.warning("thumbnail generation failed for %s", source)
        return None

    def ensure_playable(self, source: Path, workdir: Path) -> tuple[Path, MediaInfo]:
        """Return a browser-playable file (transcoding exotic codecs when needed)."""
        info = self.probe(source)
        suffix = source.suffix.lower()
        codec_ok = (info.video_codec or "").lower() in _WEB_VIDEO_CODECS if info.has_video else True
        container_ok = suffix in _WEB_CONTAINERS
        if codec_ok and container_ok:
            return source, info

        target = workdir / "playable.mp4"
        args = [
            self.tools.ffmpeg, "-hide_banner", "-nostdin", "-y",
            "-i", str(source),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        ]
        args += ["-c:a", "aac", "-b:a", "160k"] if info.has_audio else ["-an"]
        args += [str(target)]
        proc = _run(args, timeout=7200)
        if proc.returncode != 0 or not target.exists():
            raise ApiError(
                "Не удалось перекодировать видео в MP4.",
                422,
                "transcode_failed",
                {"stderr": (proc.stderr or "")[-400:]},
            )
        new_info = self.probe(target)
        new_info.duration = new_info.duration or info.duration
        return target, new_info

    def download_url(self, url: str, workdir: Path) -> Path:
        if not self.tools.ytdlp:
            raise ApiError(
                "Импорт по ссылке недоступен: положите yt-dlp.exe в tools/yt-dlp.",
                501,
                "ytdlp_missing",
            )
        workdir.mkdir(parents=True, exist_ok=True)
        template = str(workdir / "download.%(ext)s")
        ffmpeg_dir = Path(self.tools.ffmpeg).parent if self.tools.ffmpeg else None
        args = [
            self.tools.ytdlp,
            "--no-playlist",
            "--no-warnings",
            "--no-part",
            "--merge-output-format", "mp4",
            "-f",
            "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/bv*[height<=720]+ba/b",
            "-o", template,
        ]
        if ffmpeg_dir and ffmpeg_dir.is_dir():
            args += ["--ffmpeg-location", str(ffmpeg_dir)]
        args.append(url)
        proc = _run(args, timeout=3600)
        if proc.returncode != 0:
            raise ApiError(
                "Не удалось скачать видео по ссылке. Проверьте ссылку и доступ в интернет.",
                422,
                "download_failed",
                {"stderr": (proc.stderr or "")[-400:]},
            )
        candidates = [
            p for p in workdir.glob("download.*") if p.suffix.lower() not in {".part", ".ytdl"}
        ]
        if not candidates:
            raise ApiError("Сервис не вернул видеофайл.", 422, "download_empty")
        return max(candidates, key=lambda p: p.stat().st_size)


def parse_time(value: str | float | None) -> float | None:
    """Small helper used by tests and importers."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.match(r"^(\d+):(\d{2})(?::(\d{2}))?$", str(value))
    if not match:
        return None
    first, second, third = match.groups()
    if third is not None:
        return int(first) * 3600 + int(second) * 60 + int(third)
    return int(first) * 60 + int(second)
