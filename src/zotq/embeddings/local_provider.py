"""Deterministic local embedding provider."""

from __future__ import annotations

import hashlib
import math
import re


TOKEN_RE = re.compile(r"[a-z0-9]+")


class LocalEmbeddingProvider:
    """Lightweight hashing-based embedding model for local usage."""

    def __init__(self, *, model: str, dimensions: int = 256) -> None:
        if dimensions <= 0:
            raise ValueError("Embedding dimensions must be positive.")
        self._model = model or "local-hash-v1"
        self._dimensions = dimensions

    @property
    def provider_name(self) -> str:
        return "local"

    @property
    def model_name(self) -> str:
        return self._model

    def embed_text(self, text: str) -> list[float]:
        tokens = TOKEN_RE.findall((text or "").lower())
        if not tokens:
            return [0.0] * self._dimensions

        vector = [0.0] * self._dimensions
        for token in tokens:
            digest = hashlib.sha1(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], byteorder="big", signed=False) % self._dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + (digest[5] / 255.0)
            vector[index] += sign * weight

        return self._normalize(vector)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]

    def close(self) -> None:
        return None

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]
