from __future__ import annotations

from pathlib import Path

import pytest

from zotq.config import apply_cli_overrides, load_app_config
from zotq.errors import ConfigError
from zotq.models import Mode, OutputFormat, SearchMode


def write_config(path: Path) -> None:
    path.write_text(
        """
active_profile = "default"

[profiles.default]
mode = "remote"
output = "json"

[profiles.default.search]
default_mode = "semantic"
allow_fallback = false

[profiles.default.index]
enabled = true
index_dir = "~/.cache/zotq/index-file"
lexical_profile_version = 1
vector_profile_version = 1
embedding_provider = "local"
embedding_model = "local-hash-v1"
embedding_base_url = ""
embedding_api_key = ""
embedding_timeout_seconds = 20

[profiles.default.remote]
base_url = "https://example.test/api"
""".strip()
    )


def test_load_defaults_when_no_file(tmp_path: Path) -> None:
    config = load_app_config(str(tmp_path / "missing.toml"), env={})
    profile = config.require_profile("default")

    assert profile.mode == Mode.LOCAL_API
    assert profile.output == OutputFormat.TABLE
    assert profile.search.default_mode == SearchMode.KEYWORD


def test_env_overrides_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    env = {
        "ZOTQ_MODE": "local-api",
        "ZOTQ_OUTPUT": "jsonl",
        "ZOTQ_SEARCH_MODE": "keyword",
        "ZOTQ_ALLOW_FALLBACK": "true",
        "ZOTQ_EMBEDDING_PROVIDER": "ollama",
        "ZOTQ_EMBEDDING_MODEL": "nomic-embed-text",
        "ZOTQ_LEXICAL_PROFILE_VERSION": "3",
        "ZOTQ_VECTOR_PROFILE_VERSION": "4",
        "ZOTQ_EMBEDDING_BASE_URL": "http://127.0.0.1:11434",
        "ZOTQ_EMBEDDING_TIMEOUT_SECONDS": "55",
        "ZOTQ_EMBEDDING_MAX_RETRIES": "4",
    }

    config = load_app_config(str(config_path), env=env)
    profile = config.require_profile("default")

    assert profile.mode == Mode.LOCAL_API
    assert profile.output == OutputFormat.JSONL
    assert profile.search.default_mode == SearchMode.KEYWORD
    assert profile.search.allow_fallback is True
    assert profile.index.embedding_provider == "ollama"
    assert profile.index.embedding_model == "nomic-embed-text"
    assert profile.index.lexical_profile_version == 3
    assert profile.index.vector_profile_version == 4
    assert profile.index.embedding_base_url == "http://127.0.0.1:11434"
    assert profile.index.embedding_timeout_seconds == 55
    assert profile.index.embedding_max_retries == 4


def test_cli_overrides_env_and_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    env = {
        "ZOTQ_MODE": "local-api",
        "ZOTQ_OUTPUT": "jsonl",
    }

    config = load_app_config(str(config_path), env=env)
    config = apply_cli_overrides(
        config,
        profile="default",
        mode=Mode.REMOTE,
        output=OutputFormat.TABLE,
    )

    profile = config.require_profile("default")
    assert profile.mode == Mode.REMOTE
    assert profile.output == OutputFormat.TABLE


def test_cli_profile_must_exist(tmp_path: Path) -> None:
    config = load_app_config(str(tmp_path / "missing.toml"), env={})

    with pytest.raises(ConfigError):
        apply_cli_overrides(
            config,
            profile="unknown",
            mode=None,
            output=None,
        )
