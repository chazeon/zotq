"""Embedding provider factory."""

from __future__ import annotations

from ..errors import ConfigError
from ..models import IndexConfig
from .base import EmbeddingProvider
from .external_providers import GeminiEmbeddingProvider, OllamaEmbeddingProvider, OpenAIEmbeddingProvider
from .local_provider import LocalEmbeddingProvider
from .portable_provider import PortableLocalEmbeddingProvider


def build_embedding_provider(config: IndexConfig) -> EmbeddingProvider:
    provider = (config.embedding_provider or "local").strip().lower()
    model = config.embedding_model

    if provider == "local":
        model = model or "local-hash-v1"
        return LocalEmbeddingProvider(model=model)

    if provider in {"portable", "local-portable", "fastembed"}:
        return PortableLocalEmbeddingProvider(model=model or "BAAI/bge-small-en-v1.5")

    if provider == "openai":
        if not config.embedding_api_key:
            raise ConfigError("OpenAI embedding provider requires embedding_api_key.")
        return OpenAIEmbeddingProvider(
            model=model or "text-embedding-3-small",
            api_key=config.embedding_api_key,
            base_url=config.embedding_base_url or "https://api.openai.com/v1",
            timeout_seconds=config.embedding_timeout_seconds,
            max_retries=config.embedding_max_retries,
        )

    if provider == "ollama":
        return OllamaEmbeddingProvider(
            model=model or "nomic-embed-text",
            base_url=config.embedding_base_url or "http://127.0.0.1:11434",
            timeout_seconds=config.embedding_timeout_seconds,
            max_retries=config.embedding_max_retries,
        )

    if provider in {"gemini", "google", "google-gemini"}:
        if not config.embedding_api_key:
            raise ConfigError("Gemini embedding provider requires embedding_api_key.")
        return GeminiEmbeddingProvider(
            model=model or "gemini-embedding-001",
            api_key=config.embedding_api_key,
            base_url=config.embedding_base_url or "https://generativelanguage.googleapis.com/v1beta",
            timeout_seconds=config.embedding_timeout_seconds,
            max_retries=config.embedding_max_retries,
        )

    raise ConfigError(f"Unsupported embedding provider: {config.embedding_provider}")
