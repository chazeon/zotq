from __future__ import annotations

import tempfile

from zotq.client import ZotQueryClient
from zotq.index_service import MockIndexService
from zotq.models import AppConfig, BackendCapabilities, Collection, Item, QuerySpec, SearchHit, Tag


class _BatchingSourceStub:
    def __init__(self) -> None:
        self.bulk_calls = 0
        self.single_calls = 0

    def health(self) -> dict[str, str]:
        return {"status": "ok", "adapter": "stub"}

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities()

    def search_items(self, query: QuerySpec) -> list[SearchHit]:
        return []

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
        self.single_calls += 1
        return f"single:{key}"

    def get_items_bibliography(
        self,
        keys: list[str],
        *,
        style: str | None = None,
        locale: str | None = None,
        linkwrap: bool | None = None,
    ) -> str | None:
        self.bulk_calls += 1
        return "bulk-bibliography"

    def list_collections(self) -> list[Collection]:
        return []

    def list_tags(self) -> list[Tag]:
        return []


def _build_client(source: _BatchingSourceStub) -> ZotQueryClient:
    config = AppConfig()
    profile = config.profiles["default"]
    profile.index.index_dir = tempfile.mkdtemp(prefix="zotq-test-bib-batch-index-")
    return ZotQueryClient(config=config, profile_name="default", source_adapter=source, index_service=MockIndexService(profile.index))


def test_client_prefers_bulk_bibliography_fetch() -> None:
    source = _BatchingSourceStub()
    client = _build_client(source)

    entries = client.get_items_bibliography(["K1", "K2"])

    assert entries == ["bulk-bibliography"]
    assert source.bulk_calls == 1
    assert source.single_calls == 0
