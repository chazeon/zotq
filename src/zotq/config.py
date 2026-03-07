"""Configuration loading and precedence resolution."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from .errors import ConfigError
from .models import AppConfig, Mode, OutputFormat

DEFAULT_CONFIG_PATH = Path("~/.config/zotq/config.toml").expanduser()


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _env_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_overrides(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    data = env or os.environ
    out: dict[str, Any] = {}

    mode = data.get("ZOTQ_MODE")
    output = data.get("ZOTQ_OUTPUT")
    search_mode = data.get("ZOTQ_SEARCH_MODE")
    allow_fallback = data.get("ZOTQ_ALLOW_FALLBACK")

    local_base = data.get("ZOTQ_LOCAL_API_BASE_URL")
    remote_base = data.get("ZOTQ_REMOTE_BASE_URL")
    remote_token = data.get("ZOTQ_REMOTE_BEARER_TOKEN")

    index_dir = data.get("ZOTQ_INDEX_DIR")
    embedding_provider = data.get("ZOTQ_EMBEDDING_PROVIDER")
    embedding_model = data.get("ZOTQ_EMBEDDING_MODEL")
    lexical_profile_version = data.get("ZOTQ_LEXICAL_PROFILE_VERSION")
    vector_profile_version = data.get("ZOTQ_VECTOR_PROFILE_VERSION")
    embedding_base_url = data.get("ZOTQ_EMBEDDING_BASE_URL")
    embedding_api_key = data.get("ZOTQ_EMBEDDING_API_KEY")
    embedding_timeout = data.get("ZOTQ_EMBEDDING_TIMEOUT_SECONDS")
    embedding_retries = data.get("ZOTQ_EMBEDDING_MAX_RETRIES")

    profile_patch: dict[str, Any] = {}

    if mode:
        profile_patch["mode"] = mode
    if output:
        profile_patch["output"] = output

    search_patch: dict[str, Any] = {}
    if search_mode:
        search_patch["default_mode"] = search_mode
    if allow_fallback is not None:
        search_patch["allow_fallback"] = _env_bool(allow_fallback)
    if search_patch:
        profile_patch["search"] = search_patch

    index_patch: dict[str, Any] = {}
    if index_dir:
        index_patch["index_dir"] = index_dir
    if embedding_provider:
        index_patch["embedding_provider"] = embedding_provider
    if embedding_model:
        index_patch["embedding_model"] = embedding_model
    if lexical_profile_version:
        index_patch["lexical_profile_version"] = lexical_profile_version
    if vector_profile_version:
        index_patch["vector_profile_version"] = vector_profile_version
    if embedding_base_url:
        index_patch["embedding_base_url"] = embedding_base_url
    if embedding_api_key:
        index_patch["embedding_api_key"] = embedding_api_key
    if embedding_timeout:
        index_patch["embedding_timeout_seconds"] = embedding_timeout
    if embedding_retries:
        index_patch["embedding_max_retries"] = embedding_retries
    if index_patch:
        profile_patch["index"] = index_patch

    local_patch: dict[str, Any] = {}
    if local_base:
        local_patch["base_url"] = local_base
    if local_patch:
        profile_patch["local_api"] = local_patch

    remote_patch: dict[str, Any] = {}
    if remote_base:
        remote_patch["base_url"] = remote_base
    if remote_token:
        remote_patch["bearer_token"] = remote_token
    if remote_patch:
        profile_patch["remote"] = remote_patch

    if profile_patch:
        out = {
            "profiles": {
                "default": profile_patch,
            }
        }

    return out


def load_file_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except OSError as exc:
        raise ConfigError(f"Failed to read config file: {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in config file: {path}: {exc}") from exc


def load_app_config(config_path: str | None = None, env: Mapping[str, str] | None = None) -> AppConfig:
    path = Path(config_path).expanduser() if config_path else DEFAULT_CONFIG_PATH

    defaults = AppConfig().model_dump(mode="python")
    file_data = load_file_config(path)
    env_data = env_overrides(env)

    merged = _deep_merge(defaults, file_data)
    merged = _deep_merge(merged, env_data)

    try:
        return AppConfig.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(f"Configuration validation failed: {exc}") from exc


def apply_cli_overrides(
    config: AppConfig,
    *,
    profile: str | None,
    mode: Mode | None,
    output: OutputFormat | None,
) -> AppConfig:
    profile_name = profile or config.active_profile

    if profile_name not in config.profiles:
        raise ConfigError(f"Profile not found: {profile_name}")

    config.active_profile = profile_name
    selected = config.profiles[profile_name]

    if mode is not None:
        selected.mode = mode
    if output is not None:
        selected.output = output

    return config
