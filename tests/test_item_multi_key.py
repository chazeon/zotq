from __future__ import annotations

import tempfile

from zotq.client import ZotQueryClient
from zotq.index_service import MockIndexService
from zotq.models import AppConfig, BackendCapabilities, Collection, Item, QuerySpec, SearchHit, Tag


class _BatchItemsSourceStub:
    def __init__(self) -> None:
        self.batch_calls = 0
        self.single_calls = 0
        self.items = {
            "K1": Item(key="K1", title="First", citation_key="alpha2026"),
            "K2": Item(key="K2", title="Second", citation_key="beta2026"),
        }

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

    def get_items(self, keys: list[str]) -> list[Item]:
        self.batch_calls += 1
        return [self.items[key] for key in keys if key in self.items]

    def get_item(self, key: str) -> Item | None:
        self.single_calls += 1
        return self.items.get(key)

    def get_item_bibtex(self, key: str) -> str | None:
        return None

    def get_item_citation_key_rpc(self, key: str) -> str | None:
        return None

    def get_items_citation_keys_rpc(self, keys: list[str]) -> dict[str, str]:
        return {}

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


class _SingleOnlySourceStub(_BatchItemsSourceStub):
    get_items = None


def _build_client(source) -> ZotQueryClient:
    config = AppConfig()
    profile = config.profiles["default"]
    profile.index.index_dir = tempfile.mkdtemp(prefix="zotq-test-item-multi-key-")
    return ZotQueryClient(
        config=config,
        profile_name="default",
        source_adapter=source,
        index_service=MockIndexService(profile.index),
    )


def test_get_items_multi_uses_batch_transport_when_available() -> None:
    source = _BatchItemsSourceStub()
    client = _build_client(source)

    payload = client.get_items_multi(["K1", "MISSING", "K2"]).model_dump(mode="json")

    assert payload["transport"]["batch_used"] is True
    assert payload["transport"]["fallback_loop"] is False
    assert [row["key"] for row in payload["results"]] == ["K1", "MISSING", "K2"]
    assert [row["status"] for row in payload["results"]] == ["ok", "not_found", "ok"]
    assert source.batch_calls == 1
    assert source.single_calls == 0


def test_get_items_multi_falls_back_to_single_item_loop() -> None:
    source = _SingleOnlySourceStub()
    client = _build_client(source)

    payload = client.get_items_multi(["K1", "MISSING"]).model_dump(mode="json")

    assert payload["transport"]["batch_used"] is False
    assert payload["transport"]["fallback_loop"] is True
    assert [row["status"] for row in payload["results"]] == ["ok", "not_found"]
    assert source.single_calls == 2


def test_get_item_citation_keys_multi_preserves_input_order() -> None:
    source = _BatchItemsSourceStub()
    client = _build_client(source)

    payload = client.get_items_citation_keys_multi(["K2", "MISSING", "K1"], prefer="auto").model_dump(mode="json")

    assert payload["transport"]["batch_used"] is True
    assert [row["key"] for row in payload["results"]] == ["K2", "MISSING", "K1"]
    assert payload["results"][0]["citation_key"] == "beta2026"
    assert payload["results"][0]["source"] == "item.citation_key"
    assert payload["results"][1]["status"] == "not_found"
    assert payload["results"][2]["citation_key"] == "alpha2026"
