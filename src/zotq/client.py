"""High-level client orchestration for CLI commands."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from .factory import build_index_service, build_source_adapter
from .index_service import MockIndexService
from .models import AppConfig, BackendCapabilities, Collection, Item, QuerySpec, SearchMode, SearchResult, Tag
from .query_engine import QueryEngine
from .sources import SourceAdapter

ProgressCallback = Callable[[str, int, int | None], None]


class ZotQueryClient:
    """Application client that orchestrates adapter, indexing, and query policy."""

    def __init__(
        self,
        config: AppConfig,
        profile_name: str | None = None,
        *,
        source_adapter: SourceAdapter | None = None,
        index_service: MockIndexService | None = None,
    ) -> None:
        self._config = config
        self._profile_name = profile_name or config.active_profile
        self._profile = config.require_profile(self._profile_name)

        self._source = source_adapter or build_source_adapter(self._profile)
        self._index = index_service or build_index_service(self._profile)

    @property
    def profile_name(self) -> str:
        return self._profile_name

    @property
    def mode(self) -> str:
        return self._profile.mode.value

    def health(self) -> dict[str, str]:
        adapter_health = self._source.health()
        return {
            "status": adapter_health.get("status", "ok"),
            "profile": self._profile_name,
            "mode": self._profile.mode.value,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "adapter": adapter_health.get("adapter", "unknown"),
        }

    def search(self, query: QuerySpec) -> SearchResult:
        capabilities = self._source.capabilities()
        index_capabilities = self._index.capabilities()
        index_status = self._index.status()

        effective_capabilities = BackendCapabilities(
            keyword=capabilities.keyword or index_capabilities.keyword,
            fuzzy=capabilities.fuzzy or index_capabilities.fuzzy,
            semantic=capabilities.semantic and index_status.enabled and index_status.ready,
            hybrid=capabilities.hybrid and index_status.enabled and index_status.ready,
            index_status=capabilities.index_status and index_capabilities.index_status,
            index_sync=capabilities.index_sync and index_capabilities.index_sync,
            index_rebuild=capabilities.index_rebuild and index_capabilities.index_rebuild,
        )

        executed_mode = QueryEngine.resolve_execution_mode(
            requested=query.search_mode,
            capabilities=effective_capabilities,
            allow_fallback=query.allow_fallback,
        )

        executed_query = query.model_copy(deep=True)
        executed_query.search_mode = executed_mode

        if getattr(index_capabilities, executed_mode.value, False):
            hits = self._index.search(executed_query)
        else:
            hits = self._source.search_items(executed_query)

        return SearchResult(
            requested_mode=query.search_mode,
            executed_mode=executed_mode,
            limit=query.limit,
            offset=query.offset,
            total=len(hits),
            hits=hits,
        )

    def get_item(self, key: str) -> Item | None:
        return self._source.get_item(key)

    def list_collections(self) -> list[Collection]:
        return self._source.list_collections()

    def list_tags(self) -> list[Tag]:
        return self._source.list_tags()

    def index_status(self):
        return self._index.status()

    def _collect_all_items(self, *, page_size: int = 100, progress: ProgressCallback | None = None) -> list[Item]:
        items: list[Item] = []
        expected_total = self._source.count_items()
        offset = 0
        while True:
            page = self._source.list_items(limit=page_size, offset=offset)
            if not page:
                break
            items.extend(page)
            if progress is not None:
                progress("collect", len(items), expected_total)
            if len(page) < page_size:
                break
            offset += len(page)
        return items

    def index_sync(self, *, full: bool = False, progress: ProgressCallback | None = None):
        items = self._collect_all_items(progress=progress)
        return self._index.sync(items=items, full=full, progress=progress)

    def index_rebuild(self, *, progress: ProgressCallback | None = None):
        items = self._collect_all_items(progress=progress)
        return self._index.rebuild(items=items, progress=progress)
