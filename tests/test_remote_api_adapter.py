from __future__ import annotations

import respx
from httpx import Response

import pytest

from zotq.errors import ConfigError
from zotq.models import AppConfig, Mode
from zotq.sources.remote_api import RemoteApiSourceAdapter


def build_remote_adapter(*, base_url: str | None = "http://remote.test", bearer: str = "token", api_key: str = ""):
    config = AppConfig()
    profile = config.profiles["default"]
    profile.mode = Mode.REMOTE
    profile.remote.base_url = base_url or ""
    profile.remote.library_id = "0"
    profile.remote.bearer_token = bearer
    profile.remote.api_key = api_key
    return RemoteApiSourceAdapter(profile)


@respx.mock
def test_remote_adapter_sends_auth_headers() -> None:
    route = respx.get("http://remote.test/users/0/items", params={"limit": 1}).mock(return_value=Response(200, json=[]))

    adapter = build_remote_adapter(bearer="abc123", api_key="key456")
    adapter.health()

    request = route.calls[0].request
    assert request.headers.get("Authorization") == "Bearer abc123"
    assert request.headers.get("X-API-Key") == "key456"


def test_remote_adapter_requires_base_url() -> None:
    with pytest.raises(ConfigError):
        build_remote_adapter(base_url=None)
