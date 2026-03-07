"""Local Zotero API source adapter."""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from ..models import ProfileConfig
from .http_base import HttpZoteroSourceAdapter


class LocalApiSourceAdapter(HttpZoteroSourceAdapter):
    """Local API adapter backed by Zotero's local HTTP API."""

    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile
        cfg = profile.local_api
        self._library_id = cfg.library_id

        headers: dict[str, str] = {}
        if cfg.api_key:
            headers["Zotero-API-Key"] = cfg.api_key

        root_url = f"{cfg.base_url.rstrip('/')}/api/users/{cfg.library_id}"

        super().__init__(
            adapter_name="local-api",
            root_url=root_url,
            timeout_seconds=cfg.timeout_seconds,
            headers=headers,
            verify_tls=True,
            semantic_enabled=bool(profile.index.enabled),
            fuzzy_enabled=False,
        )
        self._rpc_url = f"{cfg.base_url.rstrip('/')}/better-bibtex/json-rpc"

    def get_item_citation_key_rpc(self, key: str) -> str | None:
        resolved = self.get_items_citation_keys_rpc([key])
        return resolved.get(key)

    def get_items_citation_keys_rpc(self, keys: list[str]) -> dict[str, str]:
        clean_keys = [key.strip() for key in keys if key and key.strip()]
        if not clean_keys:
            return {}
        payload = {
            "jsonrpc": "2.0",
            "method": "item.citationkey",
            "params": [[f"{self._library_id}:{key}" for key in clean_keys]],
            "id": "zotq",
        }
        try:
            response = self._client.post(self._rpc_url, json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            return {}

        if not isinstance(body, Mapping):
            return {}
        result = body.get("result")

        resolved: dict[str, str] = {}

        def _set_value(item_key: str, value: str | None) -> None:
            if value and value.strip():
                resolved[item_key] = value.strip()

        key_by_full = {f"{self._library_id}:{key}": key for key in clean_keys}

        if isinstance(result, str):
            if len(clean_keys) == 1:
                _set_value(clean_keys[0], result)
            return resolved
        if isinstance(result, list):
            for item_key, value in zip(clean_keys, result):
                if isinstance(value, str):
                    _set_value(item_key, value)
            return resolved
        if isinstance(result, Mapping):
            for result_key, value in result.items():
                normalized_key = str(result_key)
                item_key = key_by_full.get(normalized_key, normalized_key)
                if isinstance(value, str):
                    _set_value(item_key, value)
                elif isinstance(value, list):
                    for entry in value:
                        if isinstance(entry, str) and entry.strip():
                            _set_value(item_key, entry)
                            break
            return resolved

        return resolved
