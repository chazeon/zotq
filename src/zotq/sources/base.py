"""Source adapter interfaces."""

from __future__ import annotations

from typing import Protocol

from ..models import BackendCapabilities, Collection, Item, QuerySpec, SearchHit, Tag


class SourceAdapter(Protocol):
    """Adapter contract for metadata and search access."""

    def health(self) -> dict[str, str]:
        ...

    def capabilities(self) -> BackendCapabilities:
        ...

    def search_items(self, query: QuerySpec) -> list[SearchHit]:
        ...

    def list_items(self, *, limit: int = 100, offset: int = 0) -> list[Item]:
        ...

    def count_items(self) -> int | None:
        ...

    def get_item(self, key: str) -> Item | None:
        ...

    def get_item_bibtex(self, key: str) -> str | None:
        ...

    def get_item_citation_key_rpc(self, key: str) -> str | None:
        ...

    def get_items_bibtex(self, keys: list[str]) -> str | None:
        ...

    def get_item_bibliography(
        self,
        key: str,
        *,
        style: str | None = None,
        locale: str | None = None,
        linkwrap: bool | None = None,
    ) -> str | None:
        ...

    def get_items_bibliography(
        self,
        keys: list[str],
        *,
        style: str | None = None,
        locale: str | None = None,
        linkwrap: bool | None = None,
    ) -> str | None:
        ...

    def list_collections(self) -> list[Collection]:
        ...

    def list_tags(self) -> list[Tag]:
        ...
