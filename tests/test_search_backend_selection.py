from __future__ import annotations

import tempfile

import pytest

from zotq.client import ZotQueryClient
from zotq.errors import ModeNotSupportedError
from zotq.models import AppConfig, BackendCapabilities, Collection, IndexStatus, Item, QuerySpec, SearchBackend, SearchHit, SearchMode, Tag


class _SourceStub:
    def __init__(self) -> None:
        self.calls = 0
        self.queries: list[QuerySpec] = []

    def health(self) -> dict[str, str]:
        return {"status": "ok", "adapter": "stub-source"}

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(keyword=True, fuzzy=True, semantic=False, hybrid=False)

    def search_items(self, query: QuerySpec) -> list[SearchHit]:
        self.calls += 1
        self.queries.append(query.model_copy(deep=True))
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
        self.queries: list[QuerySpec] = []
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
        self.queries.append(query.model_copy(deep=True))
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


def test_search_identifier_short_circuit_source_doi() -> None:
    class _IdentifierSource(_SourceStub):
        def search_items(self, query: QuerySpec) -> list[SearchHit]:
            self.calls += 1
            self.queries.append(query.model_copy(deep=True))
            if query.doi and not query.text:
                return [SearchHit(item=Item(key="SRC-DOI", title="source doi", doi=query.doi))]
            return [SearchHit(item=Item(key="SRC-FALLBACK", title="fallback"))]

    source = _IdentifierSource()
    index = _IndexStub(keyword=True)
    client = _build_client(source, index)

    result = client.search(
        QuerySpec(
            text="mantle hydration",
            doi="doi:10.1029/2020JB020982",
            backend=SearchBackend.SOURCE,
            search_mode=SearchMode.KEYWORD,
        )
    )

    assert result.hits[0].item.key == "SRC-DOI"
    assert source.calls == 1
    assert source.queries[0].text is None
    assert source.queries[0].search_mode == SearchMode.KEYWORD
    assert index.calls == 0


def test_search_identifier_short_circuit_index_citation_key() -> None:
    class _IdentifierIndex(_IndexStub):
        def search(self, query: QuerySpec) -> list[SearchHit]:
            self.calls += 1
            self.queries.append(query.model_copy(deep=True))
            if query.citation_key and not query.text and query.search_mode == SearchMode.KEYWORD:
                return [SearchHit(item=Item(key="IDX-CK", title="index ck", citation_key=query.citation_key))]
            return [SearchHit(item=Item(key="IDX-FALLBACK", title="index fallback"))]

    source = _SourceStub()
    index = _IdentifierIndex(keyword=True, semantic=True)
    client = _build_client(source, index)

    result = client.search(
        QuerySpec(
            text="mantle hydration",
            citation_key="staceyThermodynamicsGruneisenParameter2019",
            backend=SearchBackend.INDEX,
            search_mode=SearchMode.SEMANTIC,
        )
    )

    assert result.hits[0].item.key == "IDX-CK"
    assert index.calls == 1
    assert index.queries[0].text is None
    assert index.queries[0].search_mode == SearchMode.KEYWORD
    assert source.calls == 0
    assert result.executed_mode == SearchMode.KEYWORD


def test_search_identifier_fallback_when_exact_misses() -> None:
    class _FallbackSource(_SourceStub):
        def search_items(self, query: QuerySpec) -> list[SearchHit]:
            self.calls += 1
            self.queries.append(query.model_copy(deep=True))
            if query.doi and not query.text:
                return []
            return [SearchHit(item=Item(key="SRC-NORMAL", title="normal"))]

    source = _FallbackSource()
    index = _IndexStub(keyword=True)
    client = _build_client(source, index)

    result = client.search(
        QuerySpec(
            text="mantle hydration",
            doi="10.9999/not-found",
            backend=SearchBackend.SOURCE,
            search_mode=SearchMode.KEYWORD,
        )
    )

    assert result.hits[0].item.key == "SRC-NORMAL"
    assert source.calls == 2
    assert source.queries[0].text is None
    assert source.queries[1].text == "mantle hydration"
    assert index.calls == 0


def test_search_identifier_short_circuit_auto_uses_index_route() -> None:
    class _IdentifierIndex(_IndexStub):
        def search(self, query: QuerySpec) -> list[SearchHit]:
            self.calls += 1
            self.queries.append(query.model_copy(deep=True))
            if query.doi and not query.text and query.search_mode == SearchMode.KEYWORD:
                return [SearchHit(item=Item(key="IDX-DOI", title="index doi", doi=query.doi))]
            return [SearchHit(item=Item(key="IDX-FALLBACK", title="index fallback"))]

    source = _SourceStub()
    index = _IdentifierIndex(keyword=True)
    client = _build_client(source, index)

    result = client.search(
        QuerySpec(
            text="mantle hydration",
            doi="10.1038/ngeo2326",
            backend=SearchBackend.AUTO,
            search_mode=SearchMode.KEYWORD,
        )
    )

    assert result.hits[0].item.key == "IDX-DOI"
    assert index.calls == 1
    assert index.queries[0].search_mode == SearchMode.KEYWORD
    assert source.calls == 0
