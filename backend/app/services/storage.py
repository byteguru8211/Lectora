"""Filesystem layout and safe media storage.

Everything a lecture owns lives in one directory keyed by a random id:
``storage/media/<key>/original.mp4``, ``audio.wav``, ``thumb.jpg`` …
Deleting the lecture deletes the directory, so there are no orphans.
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path

from werkzeug.datastructures import FileStorage

from ..errors import ApiError

log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    ".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi", ".mp3", ".m4a", ".wav", ".ogg",
}

_CHUNK = 1024 * 1024


class Storage:
    def __init__(self, root: Path, media_root: Path) -> None:
        self.root = Path(root)
        self.media_root = Path(media_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.media_root.mkdir(parents=True, exist_ok=True)

    # -- layout --------------------------------------------------------
    def new_key(self) -> str:
        return uuid.uuid4().hex

    def lecture_dir(self, key: str) -> Path:
        if not key or any(ch not in "0123456789abcdef" for ch in key):
            raise ApiError("Некорректный идентификатор хранилища", 400, "bad_storage_key")
        path = self.media_root / key
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path_for(self, relative: str | None) -> Path | None:
        if not relative:
            return None
        candidate = (self.root / relative).resolve()
        if not str(candidate).startswith(str(self.root.resolve())):
            raise ApiError("Некорректный путь к файлу", 400, "bad_path")
        return candidate

    def relative(self, path: Path) -> str:
        return str(Path(path).resolve().relative_to(self.root.resolve())).replace("\\", "/")

    # -- upload --------------------------------------------------------
    def save_upload(self, file: FileStorage, key: str, *, max_bytes: int) -> tuple[Path, int]:
        filename = file.filename or "video.mp4"
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise ApiError(
                f"Формат {suffix or 'без расширения'} не поддерживается. "
                "Загрузите MP4, WebM, MOV, MKV или аудиофайл.",
                415,
                "unsupported_media",
            )
        directory = self.lecture_dir(key)
        target = directory / f"original{suffix}"
        written = 0
        file.stream.seek(0)
        with open(target, "wb") as handle:
            while True:
                block = file.stream.read(_CHUNK)
                if not block:
                    break
                written += len(block)
                if written > max_bytes:
                    handle.close()
                    target.unlink(missing_ok=True)
                    raise ApiError(
                        f"Файл больше лимита {max_bytes // (1024 * 1024)} МБ",
                        413,
                        "file_too_large",
                    )
                handle.write(block)
        if written == 0:
            target.unlink(missing_ok=True)
            raise ApiError("Пустой файл", 400, "empty_file")
        return target, written

    def delete_lecture(self, key: str) -> None:
        directory = self.media_root / key
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)

    def cache_dir(self, name: str) -> Path:
        path = self.root / "cache" / name
        path.mkdir(parents=True, exist_ok=True)
        return path


def human_size(num_bytes: int | None) -> str:
    if not num_bytes:
        return "0 Б"
    size = float(num_bytes)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if size < 1024 or unit == "ТБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ТБ"


def free_disk_gb(path: Path) -> float | None:
    try:
        usage = shutil.disk_usage(path)
        return round(usage.free / (1024**3), 1)
    except OSError:  # pragma: no cover - platform dependent
        return None


def as_os_path(path: Path) -> str:
    return os.fspath(path)
