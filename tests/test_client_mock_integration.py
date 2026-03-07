from __future__ import annotations

import tempfile

import pytest

from zotq.client import ZotQueryClient
from zotq.errors import ModeNotSupportedError
from zotq.index_service import MockIndexService
from zotq.models import AppConfig, Item, QuerySpec, SearchMode
from zotq.sources.mock import MOCK_ITEMS, MockSourceAdapter


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


def test_index_sync_collect_resumes_after_collection_interruption() -> None:
    class _FlakyCollectSource(MockSourceAdapter):
        def __init__(self) -> None:
            super().__init__(semantic_enabled=True)
            self._items = [Item(key=f"K{i:03d}", item_type="journalArticle", title=f"Title {i}") for i in range(120)]
            self.offset_calls: list[int] = []
            self._failed_once = False

        def list_items(self, *, limit: int = 100, offset: int = 0) -> list[Item]:
            self.offset_calls.append(offset)
            if not self._failed_once and offset >= 100:
                self._failed_once = True
                raise RuntimeError("collect interrupted")
            return list(self._items[offset : offset + limit])

        def count_items(self) -> int | None:
            return len(self._items)

        def get_item(self, key: str) -> Item | None:
            for item in self._items:
                if item.key == key:
                    return item
            return None

    config = AppConfig()
    profile = config.profiles["default"]
    profile.index.index_dir = tempfile.mkdtemp(prefix="zotq-test-collect-resume-index-")
    source = _FlakyCollectSource()
    index = MockIndexService(profile.index)
    client = ZotQueryClient(
        config=config,
        profile_name="default",
        source_adapter=source,
        index_service=index,
    )

    with pytest.raises(RuntimeError, match="collect interrupted"):
        client.index_sync(full=False)

    first_run_calls = list(source.offset_calls)
    assert first_run_calls == [0, 100]

    status = client.index_sync(full=False)
    assert status.ready is True
    assert status.document_count == 120

    second_run_calls = source.offset_calls[len(first_run_calls) :]
    assert second_run_calls
    assert second_run_calls[0] == 100
    assert 0 not in second_run_calls

    payload = index._checkpoints.read()  # type: ignore[attr-defined]
    assert "collect" not in payload


def test_index_sync_collect_resumes_from_watermark_checkpoint_after_interruption() -> None:
    class _WatermarkCollectSource(MockSourceAdapter):
        def __init__(self) -> None:
            super().__init__(semantic_enabled=True)
            self._items = [Item(key=f"K{i:03d}", item_type="journalArticle", title=f"Title {i}") for i in range(6)]
            self.watermark_calls: list[str | None] = []
            self._failed_once = False

        def list_items(self, *, limit: int = 100, offset: int = 0) -> list[Item]:
            raise AssertionError("Offset paging should not run when watermark paging is available.")

        def list_items_watermark(self, *, limit: int = 100, watermark: str | None = None) -> tuple[list[Item], str | None]:
            self.watermark_calls.append(watermark)
            start = int(watermark) if watermark is not None else 0
            if not self._failed_once and start >= 2:
                self._failed_once = True
                raise RuntimeError("watermark interrupted")

            # Simulate source-order drift after resume by overlapping one previously seen row.
            if start >= 2:
                start -= 1
            page = list(self._items[start : start + 2])
            next_value = start + len(page)
            next_cursor = str(next_value) if next_value < len(self._items) else None
            return page, next_cursor

        def count_items(self) -> int | None:
            return len(self._items)

        def get_item(self, key: str) -> Item | None:
            for item in self._items:
                if item.key == key:
                    return item
            return None

    config = AppConfig()
    profile = config.profiles["default"]
    profile.index.index_dir = tempfile.mkdtemp(prefix="zotq-test-watermark-resume-index-")
    source = _WatermarkCollectSource()
    index = MockIndexService(profile.index)
    client = ZotQueryClient(
        config=config,
        profile_name="default",
        source_adapter=source,
        index_service=index,
    )

    with pytest.raises(RuntimeError, match="watermark interrupted"):
        client.index_sync(full=False)

    checkpoint = index._checkpoints.read()  # type: ignore[attr-defined]
    collect = checkpoint.get("collect")
    assert isinstance(collect, dict)
    assert collect.get("paging_mode") == "watermark"
    assert collect.get("next_cursor") == "2"

    first_run_calls = list(source.watermark_calls)
    assert first_run_calls == [None, "2"]

    status = client.index_sync(full=False)
    assert status.ready is True
    assert status.document_count == len(source._items)

    second_run_calls = source.watermark_calls[len(first_run_calls) :]
    assert second_run_calls
    assert second_run_calls[0] == "2"
    assert None not in second_run_calls

    payload = index._checkpoints.read()  # type: ignore[attr-defined]
    assert "collect" not in payload


def test_index_sync_profiles_only_reindexes_profile_mismatches_without_paging_source() -> None:
    class _CountingSource(MockSourceAdapter):
        def __init__(self) -> None:
            super().__init__(semantic_enabled=True)
            self.list_items_calls = 0
            self.get_item_calls: list[str] = []

        def list_items(self, *, limit: int = 100, offset: int = 0) -> list[Item]:
            self.list_items_calls += 1
            return super().list_items(limit=limit, offset=offset)

        def get_item(self, key: str) -> Item | None:
            self.get_item_calls.append(key)
            return super().get_item(key)

    base_config = AppConfig()
    base_profile = base_config.profiles["default"]
    base_profile.index.index_dir = tempfile.mkdtemp(prefix="zotq-test-profile-migrate-index-")
    base_profile.index.lexical_profile_version = 1
    base_profile.index.vector_profile_version = 1

    initial_source = _CountingSource()
    initial_index = MockIndexService(base_profile.index)
    initial_client = ZotQueryClient(
        config=base_config,
        profile_name="default",
        source_adapter=initial_source,
        index_service=initial_index,
    )
    initial_client.index_sync(full=True)

    migrated_config = AppConfig.model_validate(base_config.model_dump(mode="python"))
    migrated_profile = migrated_config.profiles["default"]
    migrated_profile.index.lexical_profile_version = 2
    migrated_profile.index.vector_profile_version = 1

    migrated_source = _CountingSource()
    migrated_index = MockIndexService(migrated_profile.index)
    migrated_client = ZotQueryClient(
        config=migrated_config,
        profile_name="default",
        source_adapter=migrated_source,
        index_service=migrated_index,
    )

    status = migrated_client.index_sync(full=False, profiles_only=True)
    inspect = migrated_client.index_inspect(sample_limit=5)

    assert status.ready is True
    assert migrated_source.list_items_calls == 0
    expected_keys = {item.key for item in MOCK_ITEMS}
    assert expected_keys.issubset(set(migrated_source.get_item_calls))
    assert inspect["profiles"]["lexical"]["mismatched"] == 0
