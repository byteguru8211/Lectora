"""Cross-encoder reranking with BAAI/bge-reranker-v2-m3 (optional but on by default)."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import numpy as np

from ..config import Config

log = logging.getLogger(__name__)


class RerankerService:
    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()
        self._failed = False

    @property
    def model_path(self) -> Path:
        return Path(Config.RERANKER_MODEL_PATH)

    def available(self) -> bool:
        return bool(Config.RERANKER_ENABLED) and self.model_path.is_dir()

    def load(self):
        if self._failed or not self.available():
            return None
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import CrossEncoder
                import torch

                torch.set_num_threads(max(1, min(8, os.cpu_count() or 4)))
                log.info("loading reranker from %s", self.model_path)
                self._model = CrossEncoder(
                    str(self.model_path), device=Config.EMBEDDING_DEVICE, max_length=256
                )
                log.info("reranker ready")
            except Exception:  # pragma: no cover - depends on weights
                log.exception("reranker failed to load; continuing without it")
                self._failed = True
                return None
        return self._model

    def warm_up(self) -> bool:
        return self.load() is not None

    def rerank(self, query: str, passages: list[str]) -> np.ndarray | None:
        if not passages:
            return None
        model = self.load()
        if model is None:
            return None
        try:
            scores = model.predict(
                [(query, passage[:420]) for passage in passages],
                batch_size=min(8, len(passages)),
                show_progress_bar=False,
            )
            return np.asarray(scores, dtype=np.float32)
        except Exception:  # pragma: no cover
            log.exception("rerank failed")
            self._failed = True
            return None


reranker = RerankerService()
