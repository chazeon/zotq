"""HTTP embedding providers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from ..errors import BackendConnectionError

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _to_float_vector(value: Any) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise BackendConnectionError("Embedding response did not include a valid vector.")
    out: list[float] = []
    for element in value:
        if not isinstance(element, (int, float)):
            raise BackendConnectionError("Embedding response contains a non-numeric vector element.")
        out.append(float(element))
    return out


def _post_with_retries(
    client: httpx.Client,
    *,
    url: str,
    json_payload: dict[str, Any],
    params: dict[str, str] | None = None,
    max_retries: int,
    context: str,
) -> httpx.Response:
    attempts = max_retries + 1
    for attempt in range(attempts):
        try:
            response = client.post(url, json=json_payload, params=params)
        except httpx.TransportError as exc:
            if attempt < max_retries:
                continue
            raise BackendConnectionError(f"{context} request failed: {exc}") from exc

        if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries:
            continue
        if response.status_code in RETRYABLE_STATUS_CODES:
            raise BackendConnectionError(f"{context} request failed: status={response.status_code}")

        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BackendConnectionError(f"{context} request failed: {exc}") from exc
        return response

    raise BackendConnectionError(f"{context} request failed after retries.")


class OpenAIEmbeddingProvider:
    """OpenAI embedding provider via REST API."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        timeout_seconds: int = 30,
        max_retries: int = 2,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._client = httpx.Client(
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def embed_text(self, text: str) -> list[float]:
        vectors = self.embed_texts([text])
        return vectors[0] if vectors else []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {
            "model": self._model,
            "input": texts,
        }
        response = _post_with_retries(
            self._client,
            url=f"{self._base_url}/embeddings",
            json_payload=payload,
            max_retries=self._max_retries,
            context="openai embedding",
        )

        body = response.json()
        data = body.get("data")
        if not isinstance(data, list):
            raise BackendConnectionError("openai embedding response missing data list.")

        vectors: list[list[float]] = []
        for row in data:
            if not isinstance(row, dict):
                raise BackendConnectionError("openai embedding response item is invalid.")
            vectors.append(_to_float_vector(row.get("embedding")))

        if len(vectors) != len(texts):
            raise BackendConnectionError("openai embedding response count mismatch.")
        return vectors

    def close(self) -> None:
        self._client.close()


class OllamaEmbeddingProvider:
    """Ollama embedding provider via local REST API."""

    def __init__(self, *, model: str, base_url: str, timeout_seconds: int = 30, max_retries: int = 2) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._client = httpx.Client(timeout=timeout_seconds)

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    def _embed_with_modern_endpoint(self, texts: list[str]) -> list[list[float]] | None:
        payload = {"model": self._model, "input": texts}
        attempts = self._max_retries + 1
        response: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                response = self._client.post(f"{self._base_url}/api/embed", json=payload)
            except httpx.TransportError as exc:
                if attempt < self._max_retries:
                    continue
                raise BackendConnectionError(f"ollama embedding request failed: {exc}") from exc

            if response.status_code == 404:
                return None
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                continue
            if response.status_code in RETRYABLE_STATUS_CODES:
                raise BackendConnectionError(f"ollama embedding request failed: status={response.status_code}")
            try:
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise BackendConnectionError(f"ollama embedding request failed: {exc}") from exc
            break

        if response is None:
            raise BackendConnectionError("ollama embedding request failed after retries.")

        body = response.json()
        embeddings = body.get("embeddings")
        if isinstance(embeddings, list):
            return [_to_float_vector(embedding) for embedding in embeddings]

        single = body.get("embedding")
        if single is not None:
            return [_to_float_vector(single)]

        raise BackendConnectionError("ollama embedding response missing embedding values.")

    def _embed_with_legacy_endpoint(self, text: str) -> list[float]:
        payload = {"model": self._model, "prompt": text}
        response = _post_with_retries(
            self._client,
            url=f"{self._base_url}/api/embeddings",
            json_payload=payload,
            max_retries=self._max_retries,
            context="ollama legacy embedding",
        )
        body = response.json()
        return _to_float_vector(body.get("embedding"))

    def embed_text(self, text: str) -> list[float]:
        vectors = self.embed_texts([text])
        return vectors[0] if vectors else []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        modern = self._embed_with_modern_endpoint(texts)
        if modern is not None:
            if len(modern) != len(texts):
                raise BackendConnectionError("ollama embedding response count mismatch.")
            return modern

        return [self._embed_with_legacy_endpoint(text) for text in texts]

    def close(self) -> None:
        self._client.close()


class GeminiEmbeddingProvider:
    """Google Gemini embedding provider via REST API."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        timeout_seconds: int = 30,
        max_retries: int = 2,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._client = httpx.Client(timeout=timeout_seconds)

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    def embed_text(self, text: str) -> list[float]:
        path = f"{self._base_url}/models/{self._model}:embedContent"
        params = {"key": self._api_key}
        payload = {"content": {"parts": [{"text": text}]}}
        response = _post_with_retries(
            self._client,
            url=path,
            params=params,
            json_payload=payload,
            max_retries=self._max_retries,
            context="gemini embedding",
        )

        body = response.json()
        embedding = body.get("embedding")
        if not isinstance(embedding, dict):
            raise BackendConnectionError("gemini embedding response missing embedding object.")
        return _to_float_vector(embedding.get("values"))

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]

    def close(self) -> None:
        self._client.close()
