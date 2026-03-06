from __future__ import annotations

import math
from pathlib import Path

import pytest

from zotq.embeddings import (
    GeminiEmbeddingProvider,
    LocalEmbeddingProvider,
    OllamaEmbeddingProvider,
    OpenAIEmbeddingProvider,
    build_embedding_provider,
)
from zotq.errors import ConfigError
from zotq.models import IndexConfig


def test_local_embedding_provider_is_deterministic_and_normalized() -> None:
    provider = LocalEmbeddingProvider(model="hash-test", dimensions=64)
    text = "mantle hydration in subduction zones"

    first = provider.embed_text(text)
    second = provider.embed_text(text)

    assert len(first) == 64
    assert first == second

    norm = math.sqrt(sum(v * v for v in first))
    assert norm == pytest.approx(1.0, rel=1e-6)


def test_local_embedding_provider_returns_zero_vector_for_empty_text() -> None:
    provider = LocalEmbeddingProvider(model="hash-test", dimensions=32)

    vector = provider.embed_text("")

    assert vector == [0.0] * 32


def test_build_embedding_provider_from_config_local() -> None:
    cfg = IndexConfig(
        enabled=True,
        index_dir=str(Path("/tmp") / "zotq-test"),
        embedding_provider="local",
        embedding_model="hash-test",
    )

    provider = build_embedding_provider(cfg)

    assert isinstance(provider, LocalEmbeddingProvider)
    assert provider.provider_name == "local"
    assert provider.model_name == "hash-test"


def test_build_embedding_provider_rejects_unknown_provider() -> None:
    cfg = IndexConfig(enabled=True, index_dir="~/.cache/zotq", embedding_provider="unknown", embedding_model="")

    with pytest.raises(ConfigError):
        build_embedding_provider(cfg)


def test_build_embedding_provider_openai_requires_api_key() -> None:
    cfg = IndexConfig(
        enabled=True,
        index_dir="~/.cache/zotq",
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_api_key="",
    )

    with pytest.raises(ConfigError):
        build_embedding_provider(cfg)


def test_build_embedding_provider_openai() -> None:
    cfg = IndexConfig(
        enabled=True,
        index_dir="~/.cache/zotq",
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_api_key="sk-test",
    )

    provider = build_embedding_provider(cfg)
    assert isinstance(provider, OpenAIEmbeddingProvider)
    assert provider.provider_name == "openai"
    assert provider.model_name == "text-embedding-3-small"


def test_build_embedding_provider_ollama() -> None:
    cfg = IndexConfig(
        enabled=True,
        index_dir="~/.cache/zotq",
        embedding_provider="ollama",
        embedding_model="nomic-embed-text",
        embedding_base_url="http://localhost:11434",
    )

    provider = build_embedding_provider(cfg)
    assert isinstance(provider, OllamaEmbeddingProvider)
    assert provider.provider_name == "ollama"
    assert provider.model_name == "nomic-embed-text"


def test_build_embedding_provider_gemini_requires_api_key() -> None:
    cfg = IndexConfig(
        enabled=True,
        index_dir="~/.cache/zotq",
        embedding_provider="gemini",
        embedding_model="gemini-embedding-001",
        embedding_api_key="",
    )

    with pytest.raises(ConfigError):
        build_embedding_provider(cfg)


def test_build_embedding_provider_gemini() -> None:
    cfg = IndexConfig(
        enabled=True,
        index_dir="~/.cache/zotq",
        embedding_provider="gemini",
        embedding_model="gemini-embedding-001",
        embedding_api_key="g-test",
    )

    provider = build_embedding_provider(cfg)
    assert isinstance(provider, GeminiEmbeddingProvider)
    assert provider.provider_name == "gemini"
    assert provider.model_name == "gemini-embedding-001"
