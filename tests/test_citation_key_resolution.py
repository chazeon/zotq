from __future__ import annotations

import tempfile

from zotq.client import ZotQueryClient
from zotq.index_service import MockIndexService
from zotq.models import AppConfig, BackendCapabilities, Collection, Item, QuerySpec, SearchHit, Tag


class _SourceStub:
    def __init__(self, *, item: Item | None, bibtex: str | None, rpc: str | None = None) -> None:
        self._item = item
        self._bibtex = bibtex
        self._rpc = rpc

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
        if self._item is None:
            return None
        return self._item if self._item.key == key else None

    def get_item_bibtex(self, key: str) -> str | None:
        return self._bibtex

    def get_item_citation_key_rpc(self, key: str) -> str | None:
        return self._rpc

    def get_items_bibtex(self, keys: list[str]) -> str | None:
        return self._bibtex

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


def _build_client(source: _SourceStub) -> ZotQueryClient:
    config = AppConfig()
    profile = config.profiles["default"]
    profile.index.index_dir = tempfile.mkdtemp(prefix="zotq-test-citekey-index-")
    return ZotQueryClient(config=config, profile_name="default", source_adapter=source, index_service=MockIndexService(profile.index))


def test_resolve_citation_key_prefers_item_field() -> None:
    source = _SourceStub(item=Item(key="K1", citation_key="fromField"), bibtex="@article{fromBibtex,}")
    client = _build_client(source)

    payload = client.get_item_citation_key("K1")

    assert payload["found"] is True
    assert payload["citation_key"] == "fromField"
    assert payload["source"] == "item.citation_key"
    assert payload["prefer"] == "auto"


def test_resolve_citation_key_falls_back_to_extra() -> None:
    source = _SourceStub(item=Item(key="K2", extra="Citation Key: fromExtra"), bibtex="@article{fromBibtex,}")
    client = _build_client(source)

    payload = client.get_item_citation_key("K2")

    assert payload["found"] is True
    assert payload["citation_key"] == "fromExtra"
    assert payload["source"] == "item.extra"
    assert payload["prefer"] == "auto"


def test_resolve_citation_key_falls_back_to_bibtex() -> None:
    source = _SourceStub(item=Item(key="K3"), bibtex="@article{fromBibtex,\n  title={X},\n}")
    client = _build_client(source)

    payload = client.get_item_citation_key("K3")

    assert payload["found"] is True
    assert payload["citation_key"] == "fromBibtex"
    assert payload["source"] == "bibtex"
    assert payload["prefer"] == "auto"


def test_resolve_citation_key_falls_back_to_rpc_before_bibtex() -> None:
    source = _SourceStub(item=Item(key="K3"), bibtex="@article{fromBibtex,\n  title={X},\n}", rpc="fromRpc")
    client = _build_client(source)

    payload = client.get_item_citation_key("K3")

    assert payload["found"] is True
    assert payload["citation_key"] == "fromRpc"
    assert payload["source"] == "rpc"
    assert payload["prefer"] == "auto"


def test_resolve_citation_key_prefer_json_does_not_fallback() -> None:
    source = _SourceStub(item=Item(key="K4", extra="Citation Key: fromExtra"), bibtex="@article{fromBibtex,}", rpc="fromRpc")
    client = _build_client(source)

    payload = client.get_item_citation_key("K4", prefer="json")

    assert payload["found"] is True
    assert payload["citation_key"] is None
    assert payload["source"] is None
    assert payload["prefer"] == "json"


def test_resolve_citation_key_prefer_extra() -> None:
    source = _SourceStub(item=Item(key="K5", extra="Citation Key: fromExtra"), bibtex="@article{fromBibtex,}", rpc="fromRpc")
    client = _build_client(source)

    payload = client.get_item_citation_key("K5", prefer="extra")

    assert payload["found"] is True
    assert payload["citation_key"] == "fromExtra"
    assert payload["source"] == "item.extra"
    assert payload["prefer"] == "extra"


def test_resolve_citation_key_prefer_rpc() -> None:
    source = _SourceStub(item=Item(key="K6"), bibtex="@article{fromBibtex,}", rpc="fromRpc")
    client = _build_client(source)

    payload = client.get_item_citation_key("K6", prefer="rpc")

    assert payload["found"] is True
    assert payload["citation_key"] == "fromRpc"
    assert payload["source"] == "rpc"
    assert payload["prefer"] == "rpc"


def test_resolve_citation_key_prefer_bibtex() -> None:
    source = _SourceStub(item=Item(key="K7"), bibtex="@article{fromBibtex,\n  title={X},\n}", rpc="fromRpc")
    client = _build_client(source)

    payload = client.get_item_citation_key("K7", prefer="bibtex")

    assert payload["found"] is True
    assert payload["citation_key"] == "fromBibtex"
    assert payload["source"] == "bibtex"
    assert payload["prefer"] == "bibtex"


def test_resolve_citation_key_prefer_is_case_insensitive() -> None:
    source = _SourceStub(item=Item(key="K7B"), bibtex="@article{fromBibtex,\n  title={X},\n}", rpc=None)
    client = _build_client(source)

    payload = client.get_item_citation_key("K7B", prefer="BIBTEX")

    assert payload["found"] is True
    assert payload["citation_key"] == "fromBibtex"
    assert payload["source"] == "bibtex"
    assert payload["prefer"] == "bibtex"


def test_resolve_citation_key_rejects_invalid_preference() -> None:
    source = _SourceStub(item=Item(key="K8", citation_key="fromField"), bibtex="@article{fromBibtex,}")
    client = _build_client(source)

    try:
        client.get_item_citation_key("K8", prefer="unknown")
    except ValueError as exc:
        assert "Unsupported citation key preference" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid citation key preference.")


def test_resolve_citation_key_handles_missing_item() -> None:
    source = _SourceStub(item=None, bibtex=None)
    client = _build_client(source)

    payload = client.get_item_citation_key("MISSING")

    assert payload["found"] is False
    assert payload["citation_key"] is None
    assert payload["source"] is None
    assert payload["prefer"] == "auto"
