from __future__ import annotations

import json
import tempfile

from click.testing import CliRunner

from zotq.cli import main


def test_index_status_includes_agentic_flag_state() -> None:
    runner = CliRunner()
    env = {
        "ZOTQ_MODE": "local-api",
        "ZOTQ_OUTPUT": "json",
        "ZOTQ_INDEX_DIR": tempfile.mkdtemp(prefix="zotq-test-agentic-status-index-"),
        "ZOTQ_VECTOR_BACKEND": "sqlite-vec",
    }

    result = runner.invoke(
        main,
        [
            "--output",
            "json",
            "--non-interactive",
            "--require-offline-ready",
            "index",
            "status",
        ],
        env=env,
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["agentic"]["non_interactive"] is True
    assert payload["agentic"]["require_offline_ready"] is True
    assert "preflight" in payload


def test_require_offline_ready_blocks_semantic_when_not_ready() -> None:
    runner = CliRunner()
    env = {
        "ZOTQ_MODE": "remote",
        "ZOTQ_REMOTE_BASE_URL": "http://remote.test",
        "ZOTQ_INDEX_DIR": tempfile.mkdtemp(prefix="zotq-test-agentic-guard-index-"),
    }

    result = runner.invoke(
        main,
        [
            "--output",
            "json",
            "--require-offline-ready",
            "search",
            "run",
            "mantle hydration",
            "--backend",
            "index",
            "--search-mode",
            "semantic",
        ],
        env=env,
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "require_offline_ready"
    preflight = payload["error"]["details"]["preflight"]
    assert preflight["offline_ready"] is False
    assert "index_not_ready" in preflight["degraded_capabilities"]
