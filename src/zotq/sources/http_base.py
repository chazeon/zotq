"""Shared HTTP adapter base class for Zotero-style APIs."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qs, urlparse

import httpx

from ..errors import BackendConnectionError
from ..models import BackendCapabilities, Collection, Item, QuerySpec, SearchHit, Tag
from .base import SourceAdapter
from .http_common import filter_items, parse_collections, parse_item, parse_items, parse_tags, to_hits


class HttpZoteroSourceAdapter(SourceAdapter):
    """Common implementation for Zotero-compatible HTTP adapters."""

    def __init__(
        self,
        *,
        adapter_name: str,
        root_url: str,
        timeout_seconds: int,
        headers: Mapping[str, str] | None,
        verify_tls: bool,
        semantic_enabled: bool,
        fuzzy_enabled: bool,
    ) -> None:
        self._adapter_name = adapter_name
        self._root_url = root_url.rstrip("/")
        self._semantic_enabled = semantic_enabled
        self._fuzzy_enabled = fuzzy_enabled
        self._client = httpx.Client(timeout=timeout_seconds, headers=dict(headers or {}), verify=verify_tls)

    def _url(self, suffix: str) -> str:
        return f"{self._root_url}/{suffix.lstrip('/')}"

    @staticmethod
    def _next_link(link_header: str | None) -> str | None:
        if not link_header:
            return None

        for part in link_header.split(","):
            segment = part.strip()
            if 'rel="next"' not in segment:
                continue
            if "<" not in segment or ">" not in segment:
                continue
            start = segment.find("<") + 1
            end = segment.find(">", start)
            if end <= start:
                continue
            return segment[start:end]
        return None

    @staticmethod
    def _start_from_url(url: str | None) -> int | None:
        if not url:
            return None
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        values = query.get("start")
        if not values:
            return None
        try:
            return int(values[0])
        except (TypeError, ValueError):
            return None

    def _get_absolute(
        self,
        url: str,
        *,
        allow_not_found: bool = False,
    ) -> httpx.Response | None:
        try:
            response = self._client.get(url)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if allow_not_found and exc.response.status_code == 404:
                return None
            raise BackendConnectionError(f"{self._adapter_name} request failed: status={exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise BackendConnectionError(f"{self._adapter_name} request failed: {exc}") from exc

    def _get(
        self,
        suffix: str,
        *,
        params: Mapping[str, object] | None = None,
        allow_not_found: bool = False,
    ) -> httpx.Response | None:
        try:
            response = self._client.get(self._url(suffix), params=params)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if allow_not_found and exc.response.status_code == 404:
                return None
            raise BackendConnectionError(
                f"{self._adapter_name} request failed for '{suffix}': status={exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise BackendConnectionError(f"{self._adapter_name} request failed for '{suffix}': {exc}") from exc

    def health(self) -> dict[str, str]:
        self._get("items", params={"limit": 1})
        return {"status": "ok", "adapter": self._adapter_name}

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            keyword=True,
            fuzzy=self._fuzzy_enabled,
            semantic=self._semantic_enabled,
            hybrid=self._semantic_enabled,
            index_status=True,
            index_sync=True,
            index_rebuild=True,
        )

    def get_item(self, key: str) -> Item | None:
        response = self._get(f"items/{key}", allow_not_found=True)
        if response is None:
            return None
        return parse_item(response.json())

    def get_item_bibtex(self, key: str) -> str | None:
        response = self._get(f"items/{key}", params={"format": "bibtex"}, allow_not_found=True)
        if response is None:
            return None
        text = response.text.strip()
        return text or None

    def get_item_citation_key_rpc(self, key: str) -> str | None:
        return None

    def get_items_bibtex(self, keys: list[str]) -> str | None:
        clean_keys = [key.strip() for key in keys if key and key.strip()]
        if not clean_keys:
            return None
        response = self._get("items", params={"itemKey": ",".join(clean_keys), "format": "bibtex"})
        if response is None:
            return None
        text = response.text.strip()
        return text or None

    def get_item_bibliography(
        self,
        key: str,
        *,
        style: str | None = None,
        locale: str | None = None,
        linkwrap: bool | None = None,
    ) -> str | None:
        params: dict[str, object] = {"format": "bib"}
        if style:
            params["style"] = style
        if locale:
            params["locale"] = locale
        if linkwrap is not None:
            params["linkwrap"] = 1 if linkwrap else 0

        response = self._get(f"items/{key}", params=params, allow_not_found=True)
        if response is None:
            return None
        text = response.text.strip()
        return text or None

    def get_items_bibliography(
        self,
        keys: list[str],
        *,
        style: str | None = None,
        locale: str | None = None,
        linkwrap: bool | None = None,
    ) -> str | None:
        clean_keys = [key.strip() for key in keys if key and key.strip()]
        if not clean_keys:
            return None

        params: dict[str, object] = {
            "itemKey": ",".join(clean_keys),
            "format": "bib",
        }
        if style:
            params["style"] = style
        if locale:
            params["locale"] = locale
        if linkwrap is not None:
            params["linkwrap"] = 1 if linkwrap else 0

        response = self._get("items", params=params)
        if response is None:
            return None
        text = response.text.strip()
        return text or None

    def count_items(self) -> int | None:
        response = self._get("items", params={"limit": 1, "start": 0})
        if response is None:
            return None
        raw = response.headers.get("Total-Results")
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def list_collections(self) -> list[Collection]:
        response = self._get("collections")
        return parse_collections(response.json() if response is not None else [])

    def list_tags(self) -> list[Tag]:
        response = self._get("tags")
        return parse_tags(response.json() if response is not None else [])

    def list_items(self, *, limit: int = 100, offset: int = 0) -> list[Item]:
        if limit <= 0:
            return []

        params: dict[str, object] = {
            "limit": min(limit, 100),
            "start": offset,
        }

        collected: list[Item] = []
        next_url: str | None = None
        current_start = offset

        while len(collected) < limit:
            if next_url is None:
                response = self._get("items", params=params)
            else:
                response = self._get_absolute(next_url)

            if response is None:
                break

            page_items = parse_items(response.json())
            if not page_items:
                break

            collected.extend(page_items)
            if len(collected) >= limit:
                break

            next_url = self._next_link(response.headers.get("Link"))
            if not next_url:
                break

            next_start = self._start_from_url(next_url)
            if next_start is None or next_start <= current_start:
                break
            current_start = next_start

        return collected[:limit]

    def search_items(self, query: QuerySpec) -> list[SearchHit]:
        suffix = f"collections/{query.collection}/items" if query.collection else "items"

        # Filters supported by Zotero API directly.
        params: dict[str, object] = {}
        if query.item_type:
            params["itemType"] = query.item_type
        if query.tags:
            # repeated query key supported by httpx via list values
            params["tag"] = query.tags

        if query.text:
            params["q"] = query.text
            params["qmode"] = "titleCreatorYear"
        elif query.title:
            params["q"] = query.title
            params["qmode"] = "title"

        # If local-only filters are requested, we need broader scan then local filtering.
        needs_local_filter_scan = bool(
            query.doi
            or query.journal
            or query.citation_key
            or query.creators
            or query.year_from is not None
            or query.year_to is not None
            or query.title is not None
        )

        page_size = max(100, query.limit)
        start = 0 if needs_local_filter_scan else query.offset
        params["limit"] = page_size
        params["start"] = start

        target_count = (query.offset + query.limit) if needs_local_filter_scan else query.limit
        collected: list[Item] = []
        next_url: str | None = None

        while True:
            if next_url is None:
                response = self._get(suffix, params=params)
            else:
                response = self._get_absolute(next_url)

            if response is None:
                break

            page_items = parse_items(response.json())
            if not page_items:
                break

            collected.extend(filter_items(page_items, query))
            if len(collected) >= target_count:
                break

            next_url = self._next_link(response.headers.get("Link"))
            if not next_url:
                break

            # Defensive break on non-advancing pagination.
            next_start = self._start_from_url(next_url)
            if next_start is not None and next_start <= start:
                break
            if next_start is not None:
                start = next_start

        if needs_local_filter_scan:
            final_items = collected[query.offset : query.offset + query.limit]
        else:
            final_items = collected[: query.limit]
        return to_hits(final_items, query)

    def close(self) -> None:
        self._client.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
