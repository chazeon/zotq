from __future__ import annotations

import json
import tempfile

from click.testing import CliRunner

from zotq.cli import main
from zotq.client import ZotQueryClient
from zotq.index_service import MockIndexService
from zotq.models import AppConfig, VectorBackend
from zotq.sources.mock import MockSourceAdapter


def _build_client(*, vector_backend: VectorBackend, embedding_provider: str = "local") -> ZotQueryClient:
    config = AppConfig()
    profile = config.profiles["default"]
    profile.index.enabled = True
    profile.index.index_dir = tempfile.mkdtemp(prefix="zotq-test-preflight-index-")
    profile.index.vector_backend = vector_backend
    profile.index.embedding_provider = embedding_provider
    profile.index.embedding_model = "local-hash-v1" if embedding_provider == "local" else "text-embedding-3-small"
    if embedding_provider == "openai":
        profile.index.embedding_api_key = "test-key"
    return ZotQueryClient(
        config=config,
        profile_name="default",
        source_adapter=MockSourceAdapter(semantic_enabled=True),
        index_service=MockIndexService(profile.index),
    )


def test_client_preflight_reports_ready_local_sqlite_vec_state() -> None:
    client = _build_client(vector_backend=VectorBackend.SQLITE_VEC, embedding_provider="local")
    client.index_sync(full=True)

    payload = client.index_preflight()

    assert payload["vector_backend"] == "sqlite-vec"
    assert payload["embedding_provider_local"] is True
    assert payload["requires_network_for_query"] is False
    assert payload["offline_ready"] is True
    assert payload["degraded_capabilities"] == []


def test_client_preflight_reports_remote_embedding_dependency() -> None:
    client = _build_client(vector_backend=VectorBackend.PYTHON, embedding_provider="openai")

    payload = client.index_preflight()

    assert payload["vector_backend"] == "python"
    assert payload["embedding_provider_local"] is False
    assert payload["requires_network_for_query"] is True
    assert payload["offline_ready"] is False
    assert "embedding_provider_remote" in payload["degraded_capabilities"]


def test_cli_index_status_includes_preflight_block() -> None:
    runner = CliRunner()
    env = {
        "ZOTQ_MODE": "local-api",
        "ZOTQ_OUTPUT": "json",
        "ZOTQ_INDEX_DIR": tempfile.mkdtemp(prefix="zotq-test-preflight-cli-index-"),
        "ZOTQ_VECTOR_BACKEND": "sqlite-vec",
    }

    result = runner.invoke(main, ["--output", "json", "index", "status"], env=env)

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "preflight" in payload
    assert payload["preflight"]["vector_backend"] == "sqlite-vec"
    assert "offline_ready" in payload["preflight"]
    assert "degraded_capabilities" in payload["preflight"]
