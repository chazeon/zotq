from __future__ import annotations

import tempfile

from zotq.client import ZotQueryClient
from zotq.index_service import MockIndexService
from zotq.models import AppConfig, BackendCapabilities, Collection, Item, QuerySpec, SearchMode, Tag


class _EnrichmentSourceStub:
    def __init__(self, *, items: list[Item], rpc: dict[str, str] | None = None, bibtex: str | None = None) -> None:
        self._items = items
        self._rpc = dict(rpc or {})
        self._bibtex = bibtex
        self.rpc_batch_calls = 0
        self.single_bibtex_calls = 0

    def health(self) -> dict[str, str]:
        return {"status": "ok", "adapter": "stub"}

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(keyword=True, fuzzy=True)

    def search_items(self, query: QuerySpec):
        return []

    def list_items(self, *, limit: int = 100, offset: int = 0) -> list[Item]:
        return list(self._items[offset : offset + limit])

    def count_items(self) -> int | None:
        return len(self._items)

    def get_item(self, key: str) -> Item | None:
        for item in self._items:
            if item.key == key:
                return item
        return None

    def get_item_bibtex(self, key: str) -> str | None:
        self.single_bibtex_calls += 1
        return None

    def get_item_citation_key_rpc(self, key: str) -> str | None:
        return self._rpc.get(key)

    def get_items_citation_keys_rpc(self, keys: list[str]) -> dict[str, str]:
        self.rpc_batch_calls += 1
        return {key: value for key, value in self._rpc.items() if key in keys}

    def get_items_bibtex(self, keys: list[str]) -> str | None:
        return self._bibtex

    def get_item_bibliography(self, key: str, *, style: str | None = None, locale: str | None = None, linkwrap: bool | None = None):
        return None

    def get_items_bibliography(
        self,
        keys: list[str],
        *,
        style: str | None = None,
        locale: str | None = None,
        linkwrap: bool | None = None,
    ):
        return None

    def list_collections(self) -> list[Collection]:
        return []

    def list_tags(self) -> list[Tag]:
        return []


def _build_client(source: _EnrichmentSourceStub) -> ZotQueryClient:
    config = AppConfig()
    profile = config.profiles["default"]
    profile.index.enabled = True
    profile.index.index_dir = tempfile.mkdtemp(prefix="zotq-test-citekey-enrich-index-")
    return ZotQueryClient(config=config, profile_name="default", source_adapter=source, index_service=MockIndexService(profile.index))


def test_index_sync_enriches_citation_key_from_batch_rpc() -> None:
    source = _EnrichmentSourceStub(
        items=[Item(key="K1", title="Doc One"), Item(key="K2", title="Doc Two")],
        rpc={"K1": "staceyThermodynamicsGruneisenParameter2019"},
    )
    client = _build_client(source)

    client.index_sync(full=True)
    result = client.search(
        QuerySpec(
            search_mode=SearchMode.KEYWORD,
            citation_key="staceythermodynamicsgruneisenparameter2019",
            limit=5,
        )
    )

    assert source.rpc_batch_calls >= 1
    assert [hit.item.key for hit in result.hits] == ["K1"]


def test_index_sync_enriches_citation_key_from_bibtex_batch_fallback() -> None:
    source = _EnrichmentSourceStub(
        items=[Item(key="K1", title="Doc One"), Item(key="K2", title="Doc Two")],
        rpc={},
        bibtex="@article{alphaKey,\n  title={Doc One}\n}\n\n@article{betaKey,\n  title={Doc Two}\n}\n",
    )
    client = _build_client(source)

    client.index_sync(full=True)
    result = client.search(QuerySpec(search_mode=SearchMode.KEYWORD, citation_key="betakey", limit=5))

    assert [hit.item.key for hit in result.hits] == ["K2"]


def test_index_sync_bibtex_batch_parse_ignores_comment_entries_without_fallback_loop() -> None:
    source = _EnrichmentSourceStub(
        items=[Item(key="K1", title="Doc One"), Item(key="K2", title="Doc Two")],
        rpc={},
        bibtex="@comment{notAKey}\n@article{alphaKey,\n  title={Doc One}\n}\n\n@article{betaKey,\n  title={Doc Two}\n}\n",
    )
    client = _build_client(source)

    client.index_sync(full=True)
    result = client.search(QuerySpec(search_mode=SearchMode.KEYWORD, citation_key="betakey", limit=5))

    assert [hit.item.key for hit in result.hits] == ["K2"]
    assert source.single_bibtex_calls == 0


def test_index_enrich_doi_updates_missing_doi_in_place() -> None:
    items = [Item(key="K1", title="Doc One"), Item(key="K2", title="Doc Two")]
    source = _EnrichmentSourceStub(items=items, rpc={})
    client = _build_client(source)

    client.index_sync(full=True)

    # Source metadata improves later; avoid expensive full sync and run targeted enrich.
    source._items[0].doi = "10.1000/xyz"
    result = client.index_enrich(field="doi")
    hits = client.search(QuerySpec(search_mode=SearchMode.KEYWORD, doi="doi:10.1000/xyz", limit=5))

    assert result["doi"]["updated"] >= 1
    assert [hit.item.key for hit in hits.hits] == ["K1"]


def test_index_enrich_journal_updates_missing_journal_in_place() -> None:
    items = [Item(key="K1", title="Doc One"), Item(key="K2", title="Doc Two")]
    source = _EnrichmentSourceStub(items=items, rpc={})
    client = _build_client(source)

    client.index_sync(full=True)

    source._items[1].journal = "Geophysical Journal International"
    result = client.index_enrich(field="journal")
    hits = client.search(QuerySpec(search_mode=SearchMode.KEYWORD, journal="geophysical journal", limit=5))

    assert result["journal"]["updated"] >= 1
    assert [hit.item.key for hit in hits.hits] == ["K2"]


def test_index_enrich_doi_reports_all_missing_not_capped_to_sample_size() -> None:
    items = [Item(key=f"K{i}", title=f"Doc {i}") for i in range(7)]
    source = _EnrichmentSourceStub(items=items, rpc={})
    client = _build_client(source)

    client.index_sync(full=True)
    # Source now exposes DOI for all records.
    for i, item in enumerate(source._items, start=1):
        item.doi = f"10.1000/test{i}"

    result = client.index_enrich(field="doi")

    assert result["doi"]["missing"] == 7
    assert result["doi"]["updated"] == 7
    assert result["doi"]["remaining"] == 0
