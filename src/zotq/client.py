"""High-level client orchestration for CLI commands."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
import re

from .factory import build_index_service, build_source_adapter
from .index_service import MockIndexService
from .models import AppConfig, BackendCapabilities, Collection, Item, QuerySpec, SearchBackend, SearchHit, SearchMode, SearchResult, Tag
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

    @staticmethod
    def _normalize_doi(value: str | None) -> str:
        raw = (value or "").strip().lower()
        if raw.startswith("https://doi.org/"):
            raw = raw[len("https://doi.org/") :]
        if raw.startswith("http://doi.org/"):
            raw = raw[len("http://doi.org/") :]
        if raw.startswith("doi:"):
            raw = raw[4:]
        return raw.strip()

    @staticmethod
    def _normalize_citation_key(value: str | None) -> str:
        return (value or "").strip().lower()

    @classmethod
    def _matches_identifier_filters(cls, item: Item, query: QuerySpec) -> bool:
        if query.doi and cls._normalize_doi(query.doi) != cls._normalize_doi(item.doi):
            return False
        if query.citation_key and cls._normalize_citation_key(query.citation_key) != cls._normalize_citation_key(item.citation_key):
            return False
        return True

    def _search_route(self, route: str, query: QuerySpec) -> list[SearchHit]:
        if route == "index":
            return self._index.search(query)
        return self._source.search_items(query)

    def _identifier_short_circuit(
        self,
        *,
        query: QuerySpec,
        route: str,
        source_capabilities: BackendCapabilities,
        index_capabilities: BackendCapabilities,
    ) -> tuple[SearchMode, list[SearchHit]] | None:
        if not query.doi and not query.citation_key:
            return None
        if route == "index" and not index_capabilities.keyword:
            return None
        if route == "source" and not source_capabilities.keyword:
            return None

        identifier_query = query.model_copy(deep=True)
        identifier_query.search_mode = SearchMode.KEYWORD
        identifier_query.text = None
        identifier_query.offset = 0
        identifier_query.limit = min(500, max(query.limit + query.offset, query.limit))

        hits = self._search_route(route, identifier_query)
        exact_hits = [hit for hit in hits if self._matches_identifier_filters(hit.item, query)]
        if not exact_hits:
            return None

        exact_hits.sort(key=lambda hit: hit.item.key)
        return SearchMode.KEYWORD, exact_hits[query.offset : query.offset + query.limit]

    def search(self, query: QuerySpec) -> SearchResult:
        source_capabilities = self._source.capabilities()
        index_capabilities = self._index.capabilities()

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

        route = forced_route or ("index" if getattr(index_capabilities, executed_mode.value, False) else "source")

        exact = self._identifier_short_circuit(
            query=query,
            route=route,
            source_capabilities=source_capabilities,
            index_capabilities=index_capabilities,
        )
        if exact is not None:
            exact_mode, exact_hits = exact
            return SearchResult(
                requested_mode=query.search_mode,
                executed_mode=exact_mode,
                limit=query.limit,
                offset=query.offset,
                total=len(exact_hits),
                hits=exact_hits,
            )

        executed_query = query.model_copy(deep=True)
        executed_query.search_mode = executed_mode

        hits = self._search_route(route, executed_query)

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

    @staticmethod
    def _citation_keys_from_bibtex_entries(bibtex: str | None) -> list[str]:
        if not bibtex:
            return []
        values = re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", bibtex)
        return [value.strip() for value in values if value and value.strip()]

    def _resolve_citation_keys_for_item_keys(
        self,
        item_keys: list[str],
        *,
        progress: ProgressCallback | None = None,
    ) -> dict[str, str]:
        clean_keys = [key.strip() for key in item_keys if key and key.strip()]
        if not clean_keys:
            return {}

        resolved: dict[str, str] = {}
        total = len(clean_keys)
        processed = 0

        batch_rpc = getattr(self._source, "get_items_citation_keys_rpc", None)
        if callable(batch_rpc):
            for start in range(0, total, 200):
                batch = clean_keys[start : start + 200]
                batch_resolved = batch_rpc(batch) or {}
                for key in batch:
                    value = batch_resolved.get(key)
                    if value and value.strip():
                        resolved[key] = value.strip()
                processed += len(batch)
                if progress is not None:
                    progress("enrich", min(processed, total), total)
        else:
            for index, key in enumerate(clean_keys, start=1):
                value = self._source.get_item_citation_key_rpc(key)
                if value and value.strip():
                    resolved[key] = value.strip()
                processed = index
                if progress is not None:
                    progress("enrich", min(processed, total), total)

        still_missing = [key for key in clean_keys if key not in resolved]
        if not still_missing:
            return resolved

        for start in range(0, len(still_missing), 100):
            batch = still_missing[start : start + 100]
            merged = self._source.get_items_bibtex(batch)
            parsed = self._citation_keys_from_bibtex_entries(merged)
            if len(parsed) == len(batch):
                for key, citation_key in zip(batch, parsed):
                    if citation_key and citation_key.strip():
                        resolved[key] = citation_key.strip()
            else:
                for key in batch:
                    citation_key = self._citation_key_from_bibtex(self._source.get_item_bibtex(key))
                    if citation_key and citation_key.strip():
                        resolved[key] = citation_key.strip()

            processed += len(batch)
            if progress is not None:
                progress("enrich", min(processed, total), total)

        return resolved

    def _enrich_field_citation_key(self, *, progress: ProgressCallback | None = None) -> dict[str, int]:
        missing = self._index.list_items_missing_field("citation_key")
        total_missing = len(missing)
        if total_missing == 0:
            return {"missing": 0, "updated": 0, "remaining": 0}

        resolved = self._resolve_citation_keys_for_item_keys(missing, progress=progress)
        updated = 0
        for item_key in missing:
            citation_key = resolved.get(item_key)
            if not citation_key:
                continue
            if self._index.set_item_citation_key(item_key, citation_key):
                updated += 1

        remaining = max(0, total_missing - updated)
        return {"missing": total_missing, "updated": updated, "remaining": remaining}

    def _enrich_field_from_source_metadata(
        self,
        field: str,
        *,
        progress: ProgressCallback | None = None,
        page_size: int = 100,
    ) -> dict[str, int]:
        if field not in {"doi", "journal"}:
            raise ValueError(f"Unsupported metadata enrichment field: {field}")

        missing_keys = self._index.list_items_missing_field(field)
        total_missing = len(missing_keys)
        if total_missing == 0:
            return {"missing": 0, "updated": 0, "remaining": 0}

        remaining_keys = set(missing_keys)
        updated = 0
        offset = 0

        while remaining_keys:
            page = self._source.list_items(limit=page_size, offset=offset)
            if not page:
                break

            for item in page:
                if item.key not in remaining_keys:
                    continue
                remaining_keys.remove(item.key)
                if field == "doi":
                    value = item.doi
                    did_update = self._index.set_item_structured_fields(item.key, doi=value) if value else False
                else:
                    value = item.journal
                    did_update = self._index.set_item_structured_fields(item.key, journal=value) if value else False
                if did_update:
                    updated += 1
                if progress is not None:
                    progress("enrich", total_missing - len(remaining_keys), total_missing)

            if len(page) < page_size:
                break
            offset += len(page)

        if progress is not None and total_missing > 0:
            progress("enrich", total_missing - len(remaining_keys), total_missing)

        remaining = max(0, total_missing - updated)
        return {"missing": total_missing, "updated": updated, "remaining": remaining}

    @staticmethod
    def _normalize_enrich_field(field: str) -> str:
        normalized = field.strip().lower().replace("_", "-")
        if normalized in {"citationkey", "citation-key"}:
            return "citation-key"
        if normalized in {"doi", "journal", "all"}:
            return normalized
        raise ValueError(f"Unsupported enrich field: {field}")

    def index_enrich(self, *, field: str = "citation-key", progress: ProgressCallback | None = None) -> dict[str, dict[str, int]]:
        selected = self._normalize_enrich_field(field)
        if selected == "all":
            field_order = ["citation-key", "doi", "journal"]
        else:
            field_order = [selected]

        results: dict[str, dict[str, int]] = {}
        for name in field_order:
            if name == "citation-key":
                results[name] = self._enrich_field_citation_key(progress=progress)
            elif name == "doi":
                results[name] = self._enrich_field_from_source_metadata("doi", progress=progress)
            elif name == "journal":
                results[name] = self._enrich_field_from_source_metadata("journal", progress=progress)
        return results

    def index_enrich_citation_keys(self, *, progress: ProgressCallback | None = None) -> dict[str, int]:
        return self._enrich_field_citation_key(progress=progress)

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

    def _collection_keys_for_export(self, collection_key: str, *, include_children: bool) -> list[str]:
        root_key = collection_key.strip()
        if not root_key:
            return []
        if not include_children:
            return [root_key]

        children_by_parent: dict[str, list[str]] = {}
        for collection in self._source.list_collections():
            parent = (collection.parent_collection or "").strip()
            if not parent:
                continue
            children_by_parent.setdefault(parent, []).append(collection.key)

        ordered: list[str] = [root_key]
        seen = {root_key}
        queue: deque[str] = deque([root_key])
        while queue:
            parent = queue.popleft()
            for child in sorted(children_by_parent.get(parent, [])):
                if child in seen:
                    continue
                seen.add(child)
                ordered.append(child)
                queue.append(child)
        return ordered

    def _collection_item_keys(self, collection_key: str, *, page_size: int) -> list[str]:
        keys: list[str] = []
        seen: set[str] = set()
        offset = 0
        while True:
            query = QuerySpec(
                backend=SearchBackend.SOURCE,
                search_mode=SearchMode.KEYWORD,
                collection=collection_key,
                limit=page_size,
                offset=offset,
            )
            hits = self._source.search_items(query)
            if not hits:
                break
            for hit in hits:
                key = hit.item.key.strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                keys.append(key)
            if len(hits) < page_size:
                break
            offset += len(hits)
        return keys

    def export_collection_bibtex(
        self,
        collection_key: str,
        *,
        include_children: bool = False,
        batch_size: int = 200,
    ) -> str:
        page_size = min(500, max(1, batch_size))
        collection_keys = self._collection_keys_for_export(collection_key, include_children=include_children)
        if not collection_keys:
            return ""

        ordered_item_keys: list[str] = []
        seen_item_keys: set[str] = set()
        for key in collection_keys:
            for item_key in self._collection_item_keys(key, page_size=page_size):
                if item_key in seen_item_keys:
                    continue
                seen_item_keys.add(item_key)
                ordered_item_keys.append(item_key)

        if not ordered_item_keys:
            return ""

        entries: list[str] = []
        for start in range(0, len(ordered_item_keys), page_size):
            batch = ordered_item_keys[start : start + page_size]
            for chunk in self.get_items_bibtex(batch):
                text = chunk.strip()
                if text:
                    entries.append(text)
        return "\n\n".join(entries)

    def list_tags(self) -> list[Tag]:
        return self._source.list_tags()

    def index_status(self):
        return self._index.status()

    def index_inspect(self, *, sample_limit: int = 5) -> dict[str, object]:
        return self._index.inspect_index(sample_limit=sample_limit)

    @staticmethod
    def _as_int(value: object, *, default: int = 0) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return default
        return default

    def _collect_all_items(
        self,
        *,
        page_size: int = 100,
        progress: ProgressCallback | None = None,
        checkpoint_scope: str = "sync",
        full: bool = False,
    ) -> list[Item]:
        items: list[Item] = []
        seen_keys: set[str] = set()
        collected_keys: list[str] = []
        expected_total = self._source.count_items()
        offset = 0

        get_collect = getattr(self._index, "get_collect_checkpoint", None)
        write_collect = getattr(self._index, "write_collect_checkpoint", None)
        clear_collect = getattr(self._index, "clear_collect_checkpoint", None)

        if callable(get_collect):
            state = get_collect()
            if isinstance(state, dict):
                scope = str(state.get("scope") or "").strip().lower()
                resume_full = bool(state.get("full", False))
                if scope == checkpoint_scope and resume_full == full:
                    offset = max(0, self._as_int(state.get("next_offset"), default=0))
                    expected_raw = state.get("expected_total")
                    if expected_raw is not None:
                        expected_total = max(0, self._as_int(expected_raw, default=0))
                    raw_keys = state.get("collected_keys")
                    if isinstance(raw_keys, list):
                        for raw_key in raw_keys:
                            key = str(raw_key).strip()
                            if not key or key in seen_keys:
                                continue
                            item = self._source.get_item(key)
                            if item is None:
                                continue
                            seen_keys.add(key)
                            collected_keys.append(key)
                            items.append(item)
                    if progress is not None:
                        progress("collect", len(items), expected_total)
                elif callable(clear_collect):
                    clear_collect()

        while True:
            page = self._source.list_items(limit=page_size, offset=offset)
            if not page:
                break
            for item in page:
                key = item.key.strip()
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                collected_keys.append(key)
                items.append(item)
            offset += len(page)
            if callable(write_collect):
                write_collect(
                    scope=checkpoint_scope,
                    full=full,
                    expected_total=expected_total,
                    next_offset=offset,
                    collected_keys=collected_keys,
                )
            if progress is not None:
                progress("collect", len(items), expected_total)
            if len(page) < page_size:
                break
        return items

    def index_sync(self, *, full: bool = False, progress: ProgressCallback | None = None):
        items = self._collect_all_items(progress=progress, checkpoint_scope="sync", full=full)
        status = self._index.sync(items=items, full=full, progress=progress)
        self.index_enrich_citation_keys(progress=progress)
        clear_collect = getattr(self._index, "clear_collect_checkpoint", None)
        if callable(clear_collect):
            clear_collect()
        return status

    def index_rebuild(self, *, progress: ProgressCallback | None = None):
        items = self._collect_all_items(progress=progress, checkpoint_scope="rebuild", full=True)
        status = self._index.rebuild(items=items, progress=progress)
        self.index_enrich_citation_keys(progress=progress)
        clear_collect = getattr(self._index, "clear_collect_checkpoint", None)
        if callable(clear_collect):
            clear_collect()
        return status
