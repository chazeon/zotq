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
        payload = {
            "jsonrpc": "2.0",
            "method": "item.citationkey",
            "params": [[f"{self._library_id}:{key}"]],
            "id": "zotq",
        }
        try:
            response = self._client.post(self._rpc_url, json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        if not isinstance(body, Mapping):
            return None
        result = body.get("result")
        if isinstance(result, str):
            return result.strip() or None
        if isinstance(result, list):
            for entry in result:
                if isinstance(entry, str) and entry.strip():
                    return entry.strip()
            return None
        if isinstance(result, Mapping):
            for candidate_key in (f"{self._library_id}:{key}", key):
                value = result.get(candidate_key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, list):
                    for entry in value:
                        if isinstance(entry, str) and entry.strip():
                            return entry.strip()
            for value in result.values():
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, list):
                    for entry in value:
                        if isinstance(entry, str) and entry.strip():
                            return entry.strip()
        return None
