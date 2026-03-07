from __future__ import annotations

import json
import tempfile

from click.testing import CliRunner

from zotq.cli import main


def _invoke_remote(runner: CliRunner, args: list[str]):
    env = {
        "ZOTQ_MODE": "remote",
        "ZOTQ_REMOTE_BASE_URL": "http://remote.test",
        "ZOTQ_INDEX_DIR": tempfile.mkdtemp(prefix="zotq-test-agentic-error-index-"),
    }
    return runner.invoke(main, args, env=env)


def test_query_conflict_emits_json_error_envelope() -> None:
    runner = CliRunner()
    result = _invoke_remote(
        runner,
        [
            "--output",
            "json",
            "search",
            "run",
            "abc",
            "--text",
            "xyz",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "query_conflict"
    assert "Pass either QUERY or --text" in payload["error"]["message"]
    assert payload["error"]["details"] == {}


def test_mode_not_supported_emits_classified_error_code() -> None:
    runner = CliRunner()
    result = _invoke_remote(
        runner,
        [
            "--output",
            "json",
            "search",
            "run",
            "mantle hydration",
            "--backend",
            "index",
            "--search-mode",
            "semantic",
            "--no-allow-fallback",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "mode_not_supported"
    assert "semantic" in payload["error"]["message"].lower()


def test_option_conflict_emits_jsonl_error_envelope() -> None:
    runner = CliRunner()
    result = _invoke_remote(
        runner,
        [
            "--output",
            "jsonl",
            "index",
            "sync",
            "--full",
            "--profiles-only",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_option_combination"
    assert payload["error"]["details"] == {}
