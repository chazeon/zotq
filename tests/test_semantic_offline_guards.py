from __future__ import annotations

from pathlib import Path

import pytest

from zotq.client import ZotQueryClient
from zotq.errors import ModeNotSupportedError
from zotq.index_service import MockIndexService
from zotq.models import AppConfig, IndexConfig, Item, QuerySpec, SearchBackend, SearchMode, VectorBackend
from zotq.sources.mock import MockSourceAdapter


def _seed_local_index(index_dir: Path) -> None:
    cfg = IndexConfig(
        enabled=True,
        index_dir=str(index_dir),
        vector_backend=VectorBackend.SQLITE_VEC,
        embedding_provider="local",
        embedding_model="local-hash-v1",
    )
    service = MockIndexService(cfg)
    try:
        service.sync(
            full=True,
            items=[
                Item(key="K1", title="Mantle hydration", abstract="Water in subducting slabs"),
                Item(key="K2", title="Core dynamics", abstract="Unrelated content"),
            ],
        )
    finally:
        service.close()


def _remote_guard_service(index_dir: Path) -> MockIndexService:
    cfg = IndexConfig(
        enabled=True,
        index_dir=str(index_dir),
        vector_backend=VectorBackend.SQLITE_VEC,
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_api_key="sk-test",
    )
    return MockIndexService(cfg)


def test_remote_embedding_dependency_disables_semantic_and_hybrid_capabilities(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    _seed_local_index(index_dir)

    service = _remote_guard_service(index_dir)
    try:
        capabilities = service.capabilities()
        assert capabilities.keyword is True
        assert capabilities.fuzzy is True
        assert capabilities.semantic is False
        assert capabilities.hybrid is False
    finally:
        service.close()


def test_semantic_query_falls_back_to_keyword_when_allowed(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    _seed_local_index(index_dir)

    config = AppConfig()
    profile = config.profiles["default"]
    profile.index.enabled = True
    profile.index.index_dir = str(index_dir)
    profile.index.vector_backend = VectorBackend.SQLITE_VEC
    profile.index.embedding_provider = "openai"
    profile.index.embedding_model = "text-embedding-3-small"
    profile.index.embedding_api_key = "sk-test"

    service = _remote_guard_service(index_dir)
    client = ZotQueryClient(
        config=config,
        profile_name="default",
        source_adapter=MockSourceAdapter(semantic_enabled=True),
        index_service=service,
    )
    try:
        result = client.search(
            QuerySpec(
                text="mantle hydration",
                backend=SearchBackend.INDEX,
                search_mode=SearchMode.SEMANTIC,
                allow_fallback=True,
                limit=5,
            )
        )
        assert result.executed_mode == SearchMode.KEYWORD
        assert result.hits
    finally:
        client.close()


def test_semantic_query_errors_without_fallback_when_remote_dependent(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    _seed_local_index(index_dir)

    config = AppConfig()
    profile = config.profiles["default"]
    profile.index.enabled = True
    profile.index.index_dir = str(index_dir)
    profile.index.vector_backend = VectorBackend.SQLITE_VEC
    profile.index.embedding_provider = "openai"
    profile.index.embedding_model = "text-embedding-3-small"
    profile.index.embedding_api_key = "sk-test"

    service = _remote_guard_service(index_dir)
    client = ZotQueryClient(
        config=config,
        profile_name="default",
        source_adapter=MockSourceAdapter(semantic_enabled=True),
        index_service=service,
    )
    try:
        with pytest.raises(ModeNotSupportedError, match="semantic"):
            client.search(
                QuerySpec(
                    text="mantle hydration",
                    backend=SearchBackend.INDEX,
                    search_mode=SearchMode.SEMANTIC,
                    allow_fallback=False,
                    limit=5,
                )
            )
    finally:
        client.close()
