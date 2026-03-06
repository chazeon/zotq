from __future__ import annotations

import pytest
import respx
from httpx import Response

from zotq.embeddings import GeminiEmbeddingProvider, OllamaEmbeddingProvider, OpenAIEmbeddingProvider
from zotq.errors import BackendConnectionError


@respx.mock
def test_openai_embed_text_uses_embeddings_endpoint() -> None:
    route = respx.post("https://api.openai.com/v1/embeddings").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1, 0.2, 0.3]},
                ]
            },
        )
    )

    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
    )
    vector = provider.embed_text("mantle hydration")

    assert vector == [0.1, 0.2, 0.3]
    assert route.called
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer sk-test"


@respx.mock
def test_openai_embed_texts_batched() -> None:
    respx.post("https://api.openai.com/v1/embeddings").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {"embedding": [1.0, 0.0]},
                    {"embedding": [0.0, 1.0]},
                ]
            },
        )
    )

    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
    )

    vectors = provider.embed_texts(["mantle", "water"])
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


@respx.mock
def test_openai_retries_on_rate_limit_then_succeeds() -> None:
    route = respx.post("https://api.openai.com/v1/embeddings").mock(
        side_effect=[
            Response(429, json={"error": {"message": "rate limited"}}),
            Response(200, json={"data": [{"embedding": [0.3, 0.7]}]}),
        ]
    )

    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
        max_retries=1,
    )
    vector = provider.embed_text("mantle hydration")

    assert vector == [0.3, 0.7]
    assert route.call_count == 2


@respx.mock
def test_openai_raises_after_retry_exhausted() -> None:
    respx.post("https://api.openai.com/v1/embeddings").mock(
        return_value=Response(500, json={"error": {"message": "server error"}})
    )

    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
        max_retries=1,
    )

    with pytest.raises(BackendConnectionError):
        provider.embed_text("mantle hydration")


@respx.mock
def test_ollama_embed_text_uses_embed_endpoint() -> None:
    route = respx.post("http://127.0.0.1:11434/api/embed").mock(
        return_value=Response(
            200,
            json={
                "embeddings": [[0.6, 0.8]],
            },
        )
    )

    provider = OllamaEmbeddingProvider(
        model="nomic-embed-text",
        base_url="http://127.0.0.1:11434",
    )
    vector = provider.embed_text("mantle hydration")

    assert vector == [0.6, 0.8]
    assert route.called


@respx.mock
def test_ollama_embed_text_falls_back_to_legacy_endpoint() -> None:
    respx.post("http://127.0.0.1:11434/api/embed").mock(return_value=Response(404, json={"error": "not found"}))
    respx.post("http://127.0.0.1:11434/api/embeddings").mock(
        return_value=Response(200, json={"embedding": [0.4, 0.2]})
    )

    provider = OllamaEmbeddingProvider(
        model="nomic-embed-text",
        base_url="http://127.0.0.1:11434",
    )
    vector = provider.embed_text("mantle hydration")
    assert vector == [0.4, 0.2]


@respx.mock
def test_ollama_retries_on_server_error_then_succeeds() -> None:
    route = respx.post("http://127.0.0.1:11434/api/embed").mock(
        side_effect=[
            Response(503, json={"error": "temporary"}),
            Response(200, json={"embeddings": [[0.5, 0.5]]}),
        ]
    )

    provider = OllamaEmbeddingProvider(
        model="nomic-embed-text",
        base_url="http://127.0.0.1:11434",
        max_retries=1,
    )
    vector = provider.embed_text("mantle hydration")
    assert vector == [0.5, 0.5]
    assert route.call_count == 2


@respx.mock
def test_gemini_embed_text_uses_embed_content_endpoint() -> None:
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key=g-test"
    ).mock(
        return_value=Response(
            200,
            json={
                "embedding": {
                    "values": [0.2, 0.5, 0.3],
                }
            },
        )
    )

    provider = GeminiEmbeddingProvider(
        model="gemini-embedding-001",
        api_key="g-test",
        base_url="https://generativelanguage.googleapis.com/v1beta",
    )
    vector = provider.embed_text("mantle hydration")
    assert vector == [0.2, 0.5, 0.3]
    assert route.called


@respx.mock
def test_gemini_retries_on_503_then_succeeds() -> None:
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key=g-test"
    ).mock(
        side_effect=[
            Response(503, json={"error": {"message": "unavailable"}}),
            Response(200, json={"embedding": {"values": [0.9, 0.1]}}),
        ]
    )

    provider = GeminiEmbeddingProvider(
        model="gemini-embedding-001",
        api_key="g-test",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        max_retries=1,
    )
    vector = provider.embed_text("mantle hydration")
    assert vector == [0.9, 0.1]
    assert route.call_count == 2
