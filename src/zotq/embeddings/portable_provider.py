"""Portable local embedding provider with explicit fastembed fallback."""

from __future__ import annotations

import importlib
from typing import Any

from .local_provider import LocalEmbeddingProvider

_DEFAULT_FALLBACK_DIMENSIONS = 256
_MODEL_FALLBACK_DIMENSIONS = {
    "baai/bge-small-en-v1.5": 384,
    "baai/bge-base-en-v1.5": 768,
    "baai/bge-large-en-v1.5": 1024,
}


def _resolve_fallback_dimensions(model: str, requested: int | None) -> int:
    if requested is not None:
        if requested <= 0:
            raise ValueError("fallback_dimensions must be positive when provided.")
        return requested

    normalized = (model or "").strip().lower()
    inferred = _MODEL_FALLBACK_DIMENSIONS.get(normalized)
    if inferred is not None:
        return inferred
    return _DEFAULT_FALLBACK_DIMENSIONS


class PortableLocalEmbeddingProvider:
    """Use fastembed when available, otherwise fallback to deterministic local hashing."""

    def __init__(self, *, model: str, fallback_dimensions: int | None = None) -> None:
        self._model = model or "BAAI/bge-small-en-v1.5"
        resolved_fallback_dimensions = _resolve_fallback_dimensions(self._model, fallback_dimensions)
        self._fallback = LocalEmbeddingProvider(model="local-hash-v1", dimensions=resolved_fallback_dimensions)
        self._fallback_dimensions = resolved_fallback_dimensions
        self._fastembed: Any | None = None
        self._fallback_active = False
        self._fallback_reason: str | None = None
        self._runtime_backend = "fastembed"

        try:
            fastembed = importlib.import_module("fastembed")
            text_embedding_cls = getattr(fastembed, "TextEmbedding", None)
            if text_embedding_cls is None:
                raise RuntimeError("fastembed.TextEmbedding is unavailable")
            self._fastembed = text_embedding_cls(model_name=self._model)
        except ModuleNotFoundError:
            self._activate_fallback("fastembed_unavailable")
        except Exception:
            self._activate_fallback("fastembed_init_failed")

    def _activate_fallback(self, reason: str) -> None:
        self._fastembed = None
        self._fallback_active = True
        self._fallback_reason = reason
        self._runtime_backend = "local-hash"

    @property
    def provider_name(self) -> str:
        return "portable-local"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def fallback_active(self) -> bool:
        return self._fallback_active

    @property
    def fallback_reason(self) -> str | None:
        return self._fallback_reason

    @property
    def runtime_backend(self) -> str:
        return self._runtime_backend

    @property
    def fallback_dimensions(self) -> int:
        return self._fallback_dimensions

    def _coerce_float_vector(self, value: Any) -> list[float]:
        if hasattr(value, "tolist"):
            return [float(v) for v in value.tolist()]
        return [float(v) for v in list(value)]

    def embed_text(self, text: str) -> list[float]:
        vectors = self.embed_texts([text])
        return vectors[0] if vectors else []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        if self._fastembed is not None:
            try:
                vectors = [self._coerce_float_vector(vector) for vector in self._fastembed.embed(texts)]
                if len(vectors) == len(texts):
                    return vectors
                self._activate_fallback("fastembed_count_mismatch")
            except Exception:
                self._activate_fallback("fastembed_runtime_failed")

        return self._fallback.embed_texts(texts)

    def close(self) -> None:
        self._fastembed = None
