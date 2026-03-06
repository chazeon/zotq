from __future__ import annotations

import tempfile

import pytest

from zotq.client import ZotQueryClient
from zotq.errors import ModeNotSupportedError
from zotq.index_service import MockIndexService
from zotq.models import AppConfig, QuerySpec, SearchMode
from zotq.sources.mock import MockSourceAdapter


def build_client(*, semantic_enabled: bool = True) -> ZotQueryClient:
    config = AppConfig()
    config.profiles["default"].index.enabled = semantic_enabled
    profile = config.profiles["default"]
    profile.index.index_dir = tempfile.mkdtemp(prefix="zotq-test-index-")
    return ZotQueryClient(
        config=config,
        profile_name="default",
        source_adapter=MockSourceAdapter(semantic_enabled=semantic_enabled),
        index_service=MockIndexService(profile.index),
    )


def test_keyword_search_returns_mock_hits() -> None:
    client = build_client()

    result = client.search(
        QuerySpec(
            text="mantle",
            search_mode=SearchMode.KEYWORD,
            limit=10,
        )
    )

    assert result.executed_mode == SearchMode.KEYWORD
    assert result.total >= 1
    assert any("mantle" in (hit.item.title or "").lower() for hit in result.hits)


def test_semantic_search_falls_back_to_keyword_when_enabled() -> None:
    client = build_client(semantic_enabled=False)

    result = client.search(
        QuerySpec(
            text="water",
            search_mode=SearchMode.SEMANTIC,
            allow_fallback=True,
            limit=10,
        )
    )

    assert result.requested_mode == SearchMode.SEMANTIC
    assert result.executed_mode == SearchMode.KEYWORD
    assert result.total >= 1


def test_semantic_search_requires_ready_index_even_if_enabled() -> None:
    client = build_client(semantic_enabled=True)

    with pytest.raises(ModeNotSupportedError):
        client.search(
            QuerySpec(
                text="water",
                search_mode=SearchMode.SEMANTIC,
                allow_fallback=False,
                limit=10,
            )
        )

    ready = client.index_sync(full=False)
    assert ready.ready is True

    result = client.search(
        QuerySpec(
            text="water",
            search_mode=SearchMode.SEMANTIC,
            allow_fallback=False,
            limit=10,
        )
    )
    assert result.executed_mode == SearchMode.SEMANTIC


def test_semantic_search_errors_without_fallback_when_unsupported() -> None:
    client = build_client(semantic_enabled=False)

    with pytest.raises(ModeNotSupportedError):
        client.search(
            QuerySpec(
                text="water",
                search_mode=SearchMode.SEMANTIC,
                allow_fallback=False,
            )
        )


def test_item_and_list_endpoints_use_mock_dataset() -> None:
    client = build_client()

    item = client.get_item("MI26RYRR")
    collections = client.list_collections()
    tags = client.list_tags()

    assert item is not None
    assert item.title == "Mantle hydration"
    assert len(collections) >= 1
    assert len(tags) >= 1


def test_index_lifecycle_updates_status() -> None:
    client = build_client()

    before = client.index_status()
    synced = client.index_sync(full=False)
    rebuilt = client.index_rebuild()

    assert before.ready is False
    assert synced.ready is True
    assert synced.document_count == 4
    assert rebuilt.ready is True
    assert rebuilt.chunk_count == 4
