"""High-level client orchestration for CLI commands."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import re

from .factory import build_index_service, build_source_adapter
from .index_service import MockIndexService
from .models import AppConfig, BackendCapabilities, Collection, Item, QuerySpec, SearchBackend, SearchMode, SearchResult, Tag
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
        source_capabilities = self._source.capabilities()
        index_capabilities = self._index.capabilities()
        index_status = self._index.status()

        if query.backend == SearchBackend.SOURCE:
            effective_capabilities = source_capabilities
            forced_route = "source"
        elif query.backend == SearchBackend.INDEX:
            effective_capabilities = index_capabilities
            forced_route = "index"
        else:
            effective_capabilities = BackendCapabilities(
                keyword=source_capabilities.keyword or index_capabilities.keyword,
                fuzzy=source_capabilities.fuzzy or index_capabilities.fuzzy,
                semantic=index_capabilities.semantic,
                hybrid=index_capabilities.hybrid,
                index_status=source_capabilities.index_status and index_capabilities.index_status,
                index_sync=source_capabilities.index_sync and index_capabilities.index_sync,
                index_rebuild=source_capabilities.index_rebuild and index_capabilities.index_rebuild,
            )
            forced_route = None

        executed_mode = QueryEngine.resolve_execution_mode(
            requested=query.search_mode,
            capabilities=effective_capabilities,
            allow_fallback=query.allow_fallback,
        )

        executed_query = query.model_copy(deep=True)
        executed_query.search_mode = executed_mode

        route = forced_route or ("index" if getattr(index_capabilities, executed_mode.value, False) else "source")
        if route == "index":
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

    @staticmethod
    def _citation_key_from_extra(extra: str | None) -> str | None:
        if not extra:
            return None
        match = re.search(r"(?im)^\s*citation\s*key\s*:\s*(\S+)\s*$", extra)
        if not match:
            return None
        return match.group(1).strip() or None

    @staticmethod
    def _citation_key_from_bibtex(bibtex: str | None) -> str | None:
        if not bibtex:
            return None
        match = re.search(r"@\w+\s*\{\s*([^,\s]+)\s*,", bibtex)
        if not match:
            return None
        return match.group(1).strip() or None

    def get_item_citation_key(self, key: str, *, prefer: str = "auto") -> dict[str, str | bool | None]:
        prefer_mode = prefer.strip().lower()
        item = self.get_item(key)
        if item is None:
            return {"found": False, "item_key": key, "citation_key": None, "source": None, "prefer": prefer_mode}

        candidates: list[tuple[str, str | None]] = [
            ("item.citation_key", item.citation_key),
            ("item.extra", self._citation_key_from_extra(item.extra)),
            ("rpc", self._source.get_item_citation_key_rpc(key)),
            ("bibtex", self._citation_key_from_bibtex(self._source.get_item_bibtex(key))),
        ]

        if prefer_mode == "auto":
            ordered = candidates
        else:
            prefer_map = {
                "json": "item.citation_key",
                "extra": "item.extra",
                "rpc": "rpc",
                "bibtex": "bibtex",
            }
            selected = prefer_map.get(prefer_mode)
            if selected is None:
                raise ValueError(f"Unsupported citation key preference: {prefer}")
            ordered = [entry for entry in candidates if entry[0] == selected]

        for source, value in ordered:
            if value and value.strip():
                return {
                    "found": True,
                    "item_key": key,
                    "citation_key": value.strip(),
                    "source": source,
                    "prefer": prefer_mode,
                }

        return {"found": True, "item_key": key, "citation_key": None, "source": None, "prefer": prefer_mode}

    def get_item_bibliography(
        self,
        key: str,
        *,
        style: str | None = None,
        locale: str | None = None,
        linkwrap: bool | None = None,
    ) -> dict[str, str | bool | None]:
        bibliography = self._source.get_item_bibliography(key, style=style, locale=locale, linkwrap=linkwrap)
        return {
            "found": bibliography is not None,
            "item_key": key,
            "style": style,
            "locale": locale,
            "linkwrap": linkwrap,
            "bibliography": bibliography,
        }

    def get_item_bibtex(self, key: str) -> str | None:
        return self._source.get_item_bibtex(key)

    def get_items_bibtex(self, keys: list[str]) -> list[str]:
        merged = self._source.get_items_bibtex(keys)
        if merged:
            return [merged]
        entries: list[str] = []
        for key in keys:
            entry = self._source.get_item_bibtex(key)
            if entry:
                entries.append(entry)
        return entries

    def get_items_bibliography(
        self,
        keys: list[str],
        *,
        style: str | None = None,
        locale: str | None = None,
        linkwrap: bool | None = None,
    ) -> list[str]:
        merged = self._source.get_items_bibliography(keys, style=style, locale=locale, linkwrap=linkwrap)
        if merged:
            return [merged]

        entries: list[str] = []
        for key in keys:
            bibliography = self._source.get_item_bibliography(key, style=style, locale=locale, linkwrap=linkwrap)
            if bibliography:
                entries.append(bibliography)
        return entries

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
