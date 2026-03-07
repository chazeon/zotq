"""Embedding providers."""

from .base import EmbeddingProvider
from .external_providers import GeminiEmbeddingProvider, OllamaEmbeddingProvider, OpenAIEmbeddingProvider
from .factory import build_embedding_provider
from .local_provider import LocalEmbeddingProvider
from .portable_provider import PortableLocalEmbeddingProvider

__all__ = [
    "EmbeddingProvider",
    "LocalEmbeddingProvider",
    "PortableLocalEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "GeminiEmbeddingProvider",
    "build_embedding_provider",
]
