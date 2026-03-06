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

    def list_collections(self) -> list[Collection]:
        ...

    def list_tags(self) -> list[Tag]:
        ...
