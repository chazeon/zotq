"""Remote Zotero-compatible API source adapter."""

from __future__ import annotations

from ..errors import ConfigError
from ..models import ProfileConfig
from .http_base import HttpZoteroSourceAdapter


class RemoteApiSourceAdapter(HttpZoteroSourceAdapter):
    """Remote API adapter with bearer/API-key auth and TLS controls."""

    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile
        cfg = profile.remote

        if not cfg.base_url:
            raise ConfigError("Remote mode requires profiles.<name>.remote.base_url")

        headers: dict[str, str] = {}
        if cfg.bearer_token:
            headers["Authorization"] = f"Bearer {cfg.bearer_token}"
        if cfg.api_key:
            headers["X-API-Key"] = cfg.api_key

        root_url = f"{cfg.base_url.rstrip('/')}/users/{cfg.library_id}"

        super().__init__(
            adapter_name="remote-api",
            root_url=root_url,
            timeout_seconds=cfg.timeout_seconds,
            headers=headers,
            verify_tls=cfg.verify_tls,
            semantic_enabled=bool(profile.index.enabled),
            fuzzy_enabled=False,
        )
