from __future__ import annotations

import tempfile

import pytest

from zotq.client import ZotQueryClient
from zotq.errors import ModeNotSupportedError
from zotq.models import AppConfig, BackendCapabilities, Collection, IndexStatus, Item, QuerySpec, SearchBackend, SearchHit, SearchMode, Tag


class _SourceStub:
    def __init__(self) -> None:
        self.calls = 0

    def health(self) -> dict[str, str]:
        return {"status": "ok", "adapter": "stub-source"}

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(keyword=True, fuzzy=True, semantic=False, hybrid=False)

    def search_items(self, query: QuerySpec) -> list[SearchHit]:
        self.calls += 1
        return [SearchHit(item=Item(key="SRC", title="source"))]

    def list_items(self, *, limit: int = 100, offset: int = 0) -> list[Item]:
        return []

    def count_items(self) -> int | None:
        return 0

    def get_item(self, key: str) -> Item | None:
        return None

    def get_item_bibtex(self, key: str) -> str | None:
        return None

    def get_items_bibtex(self, keys: list[str]) -> str | None:
        return None

    def get_item_bibliography(
        self,
        key: str,
        *,
        style: str | None = None,
        locale: str | None = None,
        linkwrap: bool | None = None,
    ) -> str | None:
        return None

    def get_items_bibliography(
        self,
        keys: list[str],
        *,
        style: str | None = None,
        locale: str | None = None,
        linkwrap: bool | None = None,
    ) -> str | None:
        return None

    def list_collections(self) -> list[Collection]:
        return []

    def list_tags(self) -> list[Tag]:
        return []


class _IndexStub:
    def __init__(self, *, keyword: bool = True, semantic: bool = False) -> None:
        self.calls = 0
        self._caps = BackendCapabilities(
            keyword=keyword,
            fuzzy=keyword,
            semantic=semantic,
            hybrid=semantic,
            index_status=True,
            index_sync=True,
            index_rebuild=True,
        )

    def capabilities(self) -> BackendCapabilities:
        return self._caps

    def status(self) -> IndexStatus:
        return IndexStatus(
            ready=self._caps.keyword,
            enabled=True,
            provider="local",
            model="local-hash-v1",
            document_count=1 if self._caps.keyword else 0,
            chunk_count=1 if self._caps.keyword else 0,
        )

    def search(self, query: QuerySpec) -> list[SearchHit]:
        self.calls += 1
        return [SearchHit(item=Item(key="IDX", title="index"))]

    def sync(self, *args, **kwargs):  # pragma: no cover
        return self.status()

    def rebuild(self, *args, **kwargs):  # pragma: no cover
        return self.status()


def _build_client(source: _SourceStub, index: _IndexStub) -> ZotQueryClient:
    config = AppConfig()
    profile = config.profiles["default"]
    profile.index.index_dir = tempfile.mkdtemp(prefix="zotq-test-backend-index-")
    return ZotQueryClient(config=config, profile_name="default", source_adapter=source, index_service=index)  # type: ignore[arg-type]


def test_search_backend_auto_prefers_index_when_available() -> None:
    source = _SourceStub()
    index = _IndexStub(keyword=True)
    client = _build_client(source, index)

    result = client.search(QuerySpec(text="x", backend=SearchBackend.AUTO, search_mode=SearchMode.KEYWORD))

    assert result.hits[0].item.key == "IDX"
    assert index.calls == 1
    assert source.calls == 0


def test_search_backend_source_forces_source_path() -> None:
    source = _SourceStub()
    index = _IndexStub(keyword=True)
    client = _build_client(source, index)

    result = client.search(QuerySpec(text="x", backend=SearchBackend.SOURCE, search_mode=SearchMode.KEYWORD))

    assert result.hits[0].item.key == "SRC"
    assert source.calls == 1
    assert index.calls == 0


def test_search_backend_index_forces_index_path() -> None:
    source = _SourceStub()
    index = _IndexStub(keyword=True)
    client = _build_client(source, index)

    result = client.search(QuerySpec(text="x", backend=SearchBackend.INDEX, search_mode=SearchMode.KEYWORD))

    assert result.hits[0].item.key == "IDX"
    assert index.calls == 1
    assert source.calls == 0


def test_search_backend_index_errors_when_mode_unsupported() -> None:
    source = _SourceStub()
    index = _IndexStub(keyword=False)
    client = _build_client(source, index)

    with pytest.raises(ModeNotSupportedError):
        client.search(QuerySpec(text="x", backend=SearchBackend.INDEX, search_mode=SearchMode.KEYWORD))
