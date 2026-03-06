from __future__ import annotations

import json
import tempfile

import respx
from click.testing import CliRunner
from httpx import Response

from zotq.cli import main


def invoke_remote(runner: CliRunner, args: list[str]):
    env = {
        "ZOTQ_MODE": "remote",
        "ZOTQ_REMOTE_BASE_URL": "http://remote.test",
        "ZOTQ_INDEX_DIR": tempfile.mkdtemp(prefix="zotq-test-cli-index-"),
    }
    return runner.invoke(main, args, env=env)


def test_root_help_lists_resource_groups() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "system" in result.output
    assert "search" in result.output
    assert "item" in result.output
    assert "collection" in result.output
    assert "tag" in result.output
    assert "index" in result.output


@respx.mock
def test_system_health_runs() -> None:
    respx.get("http://remote.test/users/0/items").mock(return_value=Response(200, json=[]))

    runner = CliRunner()
    result = invoke_remote(runner, ["--output", "json", "system", "health"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["mode"] in {"local-api", "remote"}


def test_search_run_rejects_conflicting_query_inputs() -> None:
    runner = CliRunner()
    result = invoke_remote(
        runner,
        [
            "search",
            "run",
            "abc",
            "--text",
            "xyz",
        ],
    )

    assert result.exit_code != 0
    assert "Pass either QUERY or --text" in result.output


def test_api_contract_command_emits_contract_json() -> None:
    runner = CliRunner()
    result = invoke_remote(runner, ["--output", "json", "api-contract"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    command_names = {f"{c['resource']} {c['verb']}" for c in payload["commands"]}
    assert "system health" in command_names
    assert "search run" in command_names


@respx.mock
def test_search_run_returns_hits_from_mock_adapter() -> None:
    respx.get("http://remote.test/users/0/items").mock(
        return_value=Response(
            200,
            json=[
                {
                    "key": "MI26RYRR",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Mantle hydration",
                        "date": "2015",
                        "creators": [{"firstName": "Masayuki", "lastName": "Nishi"}],
                        "tags": [{"tag": "mantle"}, {"tag": "hydration"}],
                    },
                }
            ],
        )
    )

    runner = CliRunner()
    result = invoke_remote(
        runner,
        [
            "--output",
            "json",
            "search",
            "run",
            "mantle",
            "--search-mode",
            "keyword",
            "--limit",
            "5",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["requested_mode"] == "keyword"
    assert payload["executed_mode"] == "keyword"
    assert payload["total"] >= 1
    assert len(payload["hits"]) >= 1


@respx.mock
def test_search_run_debug_emits_debug_payload() -> None:
    respx.get("http://remote.test/users/0/items").mock(
        return_value=Response(
            200,
            json=[
                {
                    "key": "MI26RYRR",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Mantle hydration",
                        "date": "2015",
                        "creators": [{"firstName": "Masayuki", "lastName": "Nishi"}],
                        "tags": [{"tag": "mantle"}, {"tag": "hydration"}],
                    },
                }
            ],
        )
    )

    runner = CliRunner()
    result = invoke_remote(
        runner,
        [
            "--output",
            "json",
            "search",
            "run",
            "mantle",
            "--search-mode",
            "keyword",
            "--debug",
            "--limit",
            "5",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    debug = payload.get("debug")
    assert isinstance(debug, dict)
    assert debug["mode"] == "keyword"
    assert debug["hit_count"] >= 1
    assert "candidate_limits" in debug
    assert isinstance(debug["hits"], list)
    assert debug["hits"][0]["item_key"] == "MI26RYRR"


@respx.mock
def test_index_sync_full_returns_ready_status() -> None:
    respx.get("http://remote.test/users/0/items").mock(
        return_value=Response(
            200,
            json=[
                {
                    "key": "MI26RYRR",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Mantle hydration",
                        "date": "2015",
                        "creators": [{"firstName": "Masayuki", "lastName": "Nishi"}],
                        "tags": [{"tag": "mantle"}],
                    },
                }
            ],
        )
    )

    runner = CliRunner()
    result = invoke_remote(runner, ["--output", "json", "index", "sync", "--full"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["action"] == "sync"
    assert payload["full"] is True
    assert payload["status"]["ready"] is True
    assert payload["status"]["chunk_count"] >= 1


@respx.mock
def test_index_sync_json_output_ignores_progress_rendering() -> None:
    respx.get("http://remote.test/users/0/items").mock(
        return_value=Response(
            200,
            json=[
                {
                    "key": "MI26RYRR",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Mantle hydration",
                        "date": "2015",
                        "creators": [{"firstName": "Masayuki", "lastName": "Nishi"}],
                        "tags": [{"tag": "mantle"}],
                    },
                }
            ],
        )
    )

    runner = CliRunner()
    result = invoke_remote(runner, ["--output", "json", "index", "sync", "--full", "--progress"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["action"] == "sync"
    assert payload["status"]["ready"] is True
