"""Local Zotero API source adapter."""

from __future__ import annotations

from ..models import ProfileConfig
from .http_base import HttpZoteroSourceAdapter


class LocalApiSourceAdapter(HttpZoteroSourceAdapter):
    """Local API adapter backed by Zotero's local HTTP API."""

    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile
        cfg = profile.local_api

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
