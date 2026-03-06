"""Embedding provider abstraction."""

from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    """Contract for embedding generation."""

    @property
    def provider_name(self) -> str:
        ...

    @property
    def model_name(self) -> str:
        ...

    def embed_text(self, text: str) -> list[float]:
        ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...

    def close(self) -> None:
        ...
