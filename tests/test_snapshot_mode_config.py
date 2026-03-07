from __future__ import annotations

from pathlib import Path

import pytest

from zotq.config import load_app_config
from zotq.errors import ConfigError
from zotq.factory import build_source_adapter
from zotq.models import Mode


def _write_snapshot(path: Path) -> Path:
    bib_path = path / "snapshot.bib"
    bib_path.write_text(
        """
@article{nishiMantleHydration2015,
  title = {Mantle hydration},
  author = {Nishi, Masayuki},
  year = {2015},
  doi = {10.1234/mantle.2015},
  journal = {Geophysical Journal}
}
""".strip()
    )
    return bib_path


def test_snapshot_mode_loads_snapshot_config_from_file(tmp_path: Path) -> None:
    bib_path = _write_snapshot(tmp_path)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
active_profile = "default"

[profiles.default]
mode = "snapshot"
output = "json"

[profiles.default.snapshot]
bib_path = "{bib_path}"
""".strip()
    )

    config = load_app_config(str(config_path), env={})
    profile = config.require_profile("default")

    assert profile.mode == Mode.SNAPSHOT
    assert profile.snapshot.bib_path == str(bib_path)


def test_snapshot_mode_supports_env_override_for_bib_path(tmp_path: Path) -> None:
    bib_path = _write_snapshot(tmp_path)
    config = load_app_config(
        str(tmp_path / "missing.toml"),
        env={
            "ZOTQ_MODE": "snapshot",
            "ZOTQ_SNAPSHOT_BIB_PATH": str(bib_path),
        },
    )

    profile = config.require_profile("default")
    assert profile.mode == Mode.SNAPSHOT
    assert profile.snapshot.bib_path == str(bib_path)


def test_snapshot_mode_requires_bib_path_for_adapter_build() -> None:
    from zotq.models import AppConfig

    config = AppConfig()
    profile = config.profiles["default"]
    profile.mode = Mode.SNAPSHOT
    profile.snapshot.bib_path = ""

    with pytest.raises(ConfigError, match="snapshot"):
        build_source_adapter(profile)
