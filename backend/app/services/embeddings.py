"""Local dense embeddings (BAAI/bge-m3) with lazy loading and query cache."""

from __future__ import annotations

import gc
import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np

from ..config import Config
from ..errors import ApiError

log = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self) -> None:
        self._model = None
        self._device: str | None = None
        self._lock = threading.Lock()
        self._query_cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._cache_limit = 256

    # -- lifecycle -----------------------------------------------------
    @property
    def model_path(self) -> Path:
        return Path(Config.EMBEDDING_MODEL_PATH)

    def available(self) -> bool:
        path = self.model_path
        if not path.is_dir():
            return False
        return any(path.glob("*.bin")) or any(path.glob("*.safetensors"))

    @staticmethod
    def resolve_device(requested: str | None = None) -> str:
        device = (requested or Config.EMBEDDING_DEVICE or "cpu").lower()
        if device.startswith("cuda"):
            try:
                import torch
                if torch.cuda.is_available():
                    return device
            except Exception:
                pass
            log.warning("CUDA requested but unavailable; falling back to CPU")
            return "cpu"
        return device

    def load(self, device: str | None = None):
        target_device = self.resolve_device(device)
        if self._model is not None and self._device == target_device:
            return self._model
        with self._lock:
            if self._model is not None and self._device == target_device:
                return self._model
            if self._model is not None:
                self._model = None
                self._device = None
                gc.collect()
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
            path = self.model_path
            if not path.is_dir():
                raise ApiError(
                    f"Модель эмбеддингов не найдена: {path}",
                    503,
                    "embedding_model_missing",
                )
            try:
                from sentence_transformers import SentenceTransformer
                import torch

                torch.set_num_threads(max(1, min(8, os.cpu_count() or 4)))
                log.info("loading embedding model from %s on %s", path, target_device)
                model = SentenceTransformer(
                    str(path), device=target_device
                )
                model.max_seq_length = 1024
                self._model = model
                self._device = target_device
                log.info("embedding model ready (dim=%s)", model.get_sentence_embedding_dimension())
            except Exception as exc:  # pragma: no cover - depends on weights
                log.exception("failed to load embedding model")
                raise ApiError(
                    "Не удалось загрузить модель эмбеддингов. Проверьте файлы в "
                    f"{path}.",
                    503,
                    "embedding_model_failed",
                    {"reason": str(exc)[:300]},
                ) from exc
        return self._model

    def warm_up(self) -> bool:
        try:
            self.load()
            return True
        except Exception:  # pragma: no cover
            log.exception("embedding warm-up failed")
            return False

    @property
    def dimension(self) -> int:
        model = self.load()
        return int(model.get_sentence_embedding_dimension())

    # -- inference -----------------------------------------------------
    def encode_documents(
        self,
        texts: list[str],
        *,
        batch_size: int | None = None,
        device: str | None = None,
        on_progress=None,
    ) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        model = self.load(device)
        vectors: list[np.ndarray] = []
        batch = batch_size or Config.EMBEDDING_BATCH_SIZE
        total = len(texts)
        for start in range(0, total, batch):
            window = texts[start : start + batch]
            chunk = model.encode(
                window,
                batch_size=batch,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            vectors.append(np.asarray(chunk, dtype=np.float32))
            if on_progress:
                on_progress(min(1.0, (start + len(window)) / total))
        return np.vstack(vectors)

    def encode_query(self, query: str) -> np.ndarray:
        key = query.strip().lower()
        cached = self._query_cache.get(key)
        if cached is not None:
            self._query_cache.move_to_end(key)
            return cached
        # Reuse the device already holding the model: otherwise a GPU-encoded
        # lecture would force a full CPU reload on the next query.
        vector = self.encode_documents([query], device=self._device)[0]
        self._query_cache[key] = vector
        if len(self._query_cache) > self._cache_limit:
            self._query_cache.popitem(last=False)
        return vector

    def to_bytes(self, vector: np.ndarray) -> bytes:
        return np.asarray(vector, dtype=np.float32).tobytes()

    def from_bytes(self, payload: bytes | None, dim: int | None = None) -> np.ndarray:
        if not payload:
            return np.zeros(dim or self.dimension, dtype=np.float32)
        return np.frombuffer(payload, dtype=np.float32)


embeddings = EmbeddingService()
