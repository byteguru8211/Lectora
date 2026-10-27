"""Application configuration.

Every setting is read from the environment (``.env`` is loaded automatically),
so the same code runs on a laptop and on a server without edits.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def _path(name: str, default: str) -> Path:
    raw = os.getenv(name, default)
    path = Path(raw)
    return path if path.is_absolute() else (BASE_DIR / path)


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


class Config:
    """Flat configuration object consumed by ``create_app`` and services."""

    # --- core ---------------------------------------------------------
    BASE_DIR = BASE_DIR
    SECRET_KEY = os.getenv("SECRET_KEY", "lectora-dev-secret-change-me")
    ENV = os.getenv("FLASK_ENV", "production")
    DEBUG = _bool("FLASK_DEBUG", False)
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = _int("PORT", 8000)

    # --- storage ------------------------------------------------------
    STORAGE_DIR = _path("STORAGE_DIR", "storage")
    MEDIA_DIR = STORAGE_DIR / "media"
    CACHE_DIR = STORAGE_DIR / "cache"
    MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 4096)
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
    MIN_FREE_DISK_GB = _float("MIN_FREE_DISK_GB", 8.0)

    # --- database -----------------------------------------------------
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://lectora:lectora@127.0.0.1:5433/lectora",
    )
    DB_POOL_SIZE = _int("DB_POOL_SIZE", 10)
    DB_ECHO = _bool("DB_ECHO", False)

    # --- models -------------------------------------------------------
    MODELS_DIR = _path("MODELS_DIR", "models")
    ASR_MODEL_ACCURATE = _path(
        "ASR_MODEL_ACCURATE", "models/vosk/vosk-model-ru-0.42"
    )
    ASR_MODEL_FAST = _path("ASR_MODEL_FAST", "models/vosk/vosk-model-small-ru-0.22")
    ASR_DEFAULT_PROFILE = os.getenv("ASR_DEFAULT_PROFILE", "accurate")
    ASR_KEEP_WARM = _bool("ASR_KEEP_WARM", False)
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
    WHISPER_MODEL_DIR = _path("WHISPER_MODEL_DIR", "models/whisper")
    WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8_float16")
    ASR_SAMPLE_RATE = 16000

    EMBEDDING_MODEL_PATH = _path(
        "EMBEDDING_MODEL_PATH", "models/embeddings/bge-m3"
    )
    EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")
    EMBEDDING_BATCH_SIZE = _int("EMBEDDING_BATCH_SIZE", 16)

    RERANKER_MODEL_PATH = _path(
        "RERANKER_MODEL_PATH", "models/reranker/bge-reranker-v2-m3"
    )
    RERANKER_ENABLED = _bool("RERANKER_ENABLED", True)
    RERANKER_TOP_K = _int("RERANKER_TOP_K", 6)

    # --- LLM modes ----------------------------------------------------
    # api | local | offline — the default for new lectures. Users can still
    # pick another mode per lecture in the upload dialog.
    LLM_DEFAULT_MODE = (
        os.getenv("LLM_DEFAULT_MODE") or os.getenv("LLM_MODE") or "local"
    ).strip().lower()

    # --- local LLM ----------------------------------------------------
    LLM_ENABLED = _bool("LLM_ENABLED", True)
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/")
    LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5-7b-instruct")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "local")
    LLM_TIMEOUT = _float("LLM_TIMEOUT", 180.0)
    LLM_MAX_TOKENS = _int("LLM_MAX_TOKENS", 1400)
    LLM_TEMPERATURE = _float("LLM_TEMPERATURE", 0.2)
    LLM_CTX_WINDOW = _int("LLM_CTX_WINDOW", 8192)

    # --- DeepSeek Web API (via tools/FreeDeepseekAPI) ------------------
    # The proxy drives a personal DeepSeek account, so defaults are polite:
    # one request at a time, a pause between calls and bounded prompt sizes.
    API_LLM_ENABLED = _bool("API_LLM_ENABLED", True)
    API_LLM_BASE_URL = os.getenv(
        "API_LLM_BASE_URL", "http://127.0.0.1:9655/v1"
    ).rstrip("/")
    API_LLM_MODEL = os.getenv("API_LLM_MODEL", "deepseek-v4-flash")
    API_LLM_KEY = os.getenv("API_LLM_KEY", "")
    API_LLM_TIMEOUT = _float("API_LLM_TIMEOUT", 600.0)
    API_LLM_MAX_TOKENS = _int("API_LLM_MAX_TOKENS", 8192)
    API_LLM_TEMPERATURE = _float("API_LLM_TEMPERATURE", 0.3)
    API_LLM_MAX_PROMPT_CHARS = _int("API_LLM_MAX_PROMPT_CHARS", 42000)
    API_LLM_MAX_INPUT_CHARS = _int("API_LLM_MAX_INPUT_CHARS", 34000)
    API_LLM_MAP_WINDOW_CHARS = _int("API_LLM_MAP_WINDOW_CHARS", 12000)
    API_LLM_MAX_MAP_WINDOWS = _int("API_LLM_MAX_MAP_WINDOWS", 16)
    API_LLM_DETAILS_BATCH_CHARS = _int("API_LLM_DETAILS_BATCH_CHARS", 9000)
    API_LLM_MIN_INTERVAL_SEC = _float("API_LLM_MIN_INTERVAL_SEC", 3.0)
    API_LLM_MAX_CONCURRENT = _int("API_LLM_MAX_CONCURRENT", 1)
    API_LLM_RETRY_ATTEMPTS = _int("API_LLM_RETRY_ATTEMPTS", 3)
    API_LLM_RETRY_BASE_SEC = _float("API_LLM_RETRY_BASE_SEC", 4.0)
    API_LLM_RETRY_MAX_SEC = _float("API_LLM_RETRY_MAX_SEC", 90.0)
    API_LLM_QUEUE_TIMEOUT_SEC = _float("API_LLM_QUEUE_TIMEOUT_SEC", 900.0)
    API_LLM_SESSION_PREFIX = os.getenv("API_LLM_SESSION_PREFIX", "lectora")
    API_LLM_RESET_SESSION = _bool("API_LLM_RESET_SESSION", True)
    API_LLM_NOTES_MIN_SECTIONS = _int("API_LLM_NOTES_MIN_SECTIONS", 6)
    API_LLM_NOTES_MAX_SECTIONS = _int("API_LLM_NOTES_MAX_SECTIONS", 14)
    API_LLM_SUMMARY_MIN_WORDS = _int("API_LLM_SUMMARY_MIN_WORDS", 140)

    # --- tools --------------------------------------------------------
    TOOLS_DIR = _path("TOOLS_DIR", "tools")
    FFMPEG_BIN = os.getenv("FFMPEG_BIN", "")
    FFPROBE_BIN = os.getenv("FFPROBE_BIN", "")
    YTDLP_BIN = os.getenv("YTDLP_BIN", "")
    ALLOW_URL_IMPORT = _bool("ALLOW_URL_IMPORT", True)

    # --- pipeline -----------------------------------------------------
    ASR_THREADS = _int("ASR_THREADS", max(1, (os.cpu_count() or 4) // 2))
    WORKER_THREADS = _int("WORKER_THREADS", 1)
    START_WORKER = _bool("START_WORKER", True)
    WARMUP = _bool("WARMUP", True)
    PUNCTUATION_MODE = os.getenv("PUNCTUATION_MODE", "rules")  # rules|llm|none
    SUMMARY_MAX_INPUT_CHARS = _int("SUMMARY_MAX_INPUT_CHARS", 14000)
    SEGMENT_PAUSE_SEC = _float("SEGMENT_PAUSE_SEC", 0.7)
    SEGMENT_MAX_SEC = _float("SEGMENT_MAX_SEC", 9.0)
    CHUNK_MAX_CHARS = _int("CHUNK_MAX_CHARS", 1200)
    CHUNK_MAX_SEC = _float("CHUNK_MAX_SEC", 60.0)
    CHUNK_OVERLAP_SEGMENTS = _int("CHUNK_OVERLAP_SEGMENTS", 1)

    # --- search -------------------------------------------------------
    SEARCH_DEFAULT_LIMIT = _int("SEARCH_DEFAULT_LIMIT", 15)
    SEARCH_MAX_LIMIT = _int("SEARCH_MAX_LIMIT", 50)
    SEARCH_CANDIDATES = _int("SEARCH_CANDIDATES", 40)
    SEARCH_LEXICAL_WEIGHT = _float("SEARCH_LEXICAL_WEIGHT", 0.35)

    # --- misc ---------------------------------------------------------
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    FRONTEND_DIST = _path("FRONTEND_DIST", "frontend/dist")
    QA_HISTORY_LIMIT = _int("QA_HISTORY_LIMIT", 40)
