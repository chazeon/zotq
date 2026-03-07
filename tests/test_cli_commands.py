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
def test_search_run_accepts_doi_journal_and_citation_key_flags() -> None:
    respx.get("http://remote.test/users/0/items").mock(
        return_value=Response(
            200,
            json=[
                {
                    "key": "XVMVWQZX",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Thermodynamics with the Gruneisen parameter",
                        "date": "2019",
                        "DOI": "10.1016/j.pepi.2018.10.006",
                        "publicationTitle": "Physics of the Earth and Planetary Interiors",
                        "citationKey": "staceyThermodynamicsGruneisenParameter2019",
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
            "--doi",
            "doi:10.1016/j.pepi.2018.10.006",
            "--journal",
            "planetary interiors",
            "--citation-key",
            "staceythermodynamicsgruneisenparameter2019",
            "--limit",
            "5",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["query"]["doi"] == "doi:10.1016/j.pepi.2018.10.006"
    assert payload["query"]["journal"] == "planetary interiors"
    assert payload["query"]["citation_key"] == "staceythermodynamicsgruneisenparameter2019"
    assert payload["query"]["backend"] == "auto"


@respx.mock
def test_search_run_accepts_backend_flag() -> None:
    respx.get("http://remote.test/users/0/items").mock(return_value=Response(200, json=[]))

    runner = CliRunner()
    result = invoke_remote(
        runner,
        [
            "--output",
            "json",
            "search",
            "run",
            "mantle",
            "--backend",
            "source",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["query"]["backend"] == "source"


@respx.mock
def test_search_run_accepts_bibkey_alias_flag() -> None:
    respx.get("http://remote.test/users/0/items").mock(return_value=Response(200, json=[]))

    runner = CliRunner()
    result = invoke_remote(
        runner,
        [
            "--output",
            "json",
            "search",
            "run",
            "--bibkey",
            "staceyThermodynamicsGruneisenParameter2019",
            "--limit",
            "5",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["query"]["citation_key"] == "staceyThermodynamicsGruneisenParameter2019"


@respx.mock
def test_item_citekey_returns_citation_key() -> None:
    respx.get("http://remote.test/users/0/items/XVMVWQZX").mock(
        return_value=Response(
            200,
            json={
                "key": "XVMVWQZX",
                "data": {
                    "itemType": "journalArticle",
                    "title": "Thermodynamics with the Gruneisen parameter",
                    "citationKey": "staceyThermodynamicsGruneisenParameter2019",
                },
            },
        )
    )

    runner = CliRunner()
    result = invoke_remote(runner, ["--output", "json", "item", "citekey", "XVMVWQZX"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["found"] is True
    assert payload["item_key"] == "XVMVWQZX"
    assert payload["citation_key"] == "staceyThermodynamicsGruneisenParameter2019"
    assert payload["source"] == "item.citation_key"
    assert payload["prefer"] == "auto"


@respx.mock
def test_item_citekey_supports_prefer_bibtex() -> None:
    respx.get("http://remote.test/users/0/items/XVMVWQZX", params={"format": "bibtex"}).mock(
        return_value=Response(200, text="@article{staceyFromBibtex2019,}")
    )
    respx.get("http://remote.test/users/0/items/XVMVWQZX").mock(
        return_value=Response(
            200,
            json={
                "key": "XVMVWQZX",
                "data": {
                    "itemType": "journalArticle",
                    "title": "Thermodynamics with the Gruneisen parameter",
                    "citationKey": "staceyThermodynamicsGruneisenParameter2019",
                },
            },
        )
    )

    runner = CliRunner()
    result = invoke_remote(
        runner,
        ["--output", "json", "item", "citekey", "XVMVWQZX", "--prefer", "bibtex"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["found"] is True
    assert payload["citation_key"] == "staceyFromBibtex2019"
    assert payload["source"] == "bibtex"
    assert payload["prefer"] == "bibtex"


@respx.mock
def test_item_get_bib_output_uses_bibliography_endpoint() -> None:
    respx.get(
        "http://remote.test/users/0/items/XVMVWQZX",
        params={"format": "bib", "style": "apa", "locale": "en-US", "linkwrap": 1},
    ).mock(return_value=Response(200, text="<div class='csl-entry'>Stacey and Hodgkinson (2019)</div>"))

    runner = CliRunner()
    result = invoke_remote(
        runner,
        [
            "--output",
            "bib",
            "item",
            "get",
            "XVMVWQZX",
            "--style",
            "apa",
            "--locale",
            "en-US",
            "--linkwrap",
        ],
    )

    assert result.exit_code == 0
    assert "Stacey and Hodgkinson" in result.output


@respx.mock
def test_search_run_bib_output_joins_bibliography_entries() -> None:
    respx.get(
        "http://remote.test/users/0/items",
        params={"q": "ref", "qmode": "titleCreatorYear", "limit": 100, "start": 0},
    ).mock(
        return_value=Response(
            200,
            json=[
                {"key": "K1", "data": {"itemType": "journalArticle", "title": "First"}},
                {"key": "K2", "data": {"itemType": "journalArticle", "title": "Second"}},
            ],
        )
    )
    respx.get("http://remote.test/users/0/items", params={"itemKey": "K1,K2", "format": "bib"}).mock(
        return_value=Response(200, text="<div class='csl-entry'>First Ref</div>\n<div class='csl-entry'>Second Ref</div>")
    )

    runner = CliRunner()
    result = invoke_remote(
        runner,
        [
            "--output",
            "bib",
            "search",
            "run",
            "ref",
            "--search-mode",
            "keyword",
            "--limit",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert "First Ref" in result.output
    assert "Second Ref" in result.output


@respx.mock
def test_item_get_bibtex_output_uses_bibtex_endpoint() -> None:
    respx.get("http://remote.test/users/0/items/XVMVWQZX", params={"format": "bibtex"}).mock(
        return_value=Response(200, text="@article{staceyThermodynamicsGruneisenParameter2019,}")
    )

    runner = CliRunner()
    result = invoke_remote(
        runner,
        [
            "--output",
            "bibtex",
            "item",
            "get",
            "XVMVWQZX",
        ],
    )

    assert result.exit_code == 0
    assert "@article{staceyThermodynamicsGruneisenParameter2019" in result.output


@respx.mock
def test_search_run_bibtex_output_uses_batch_bibtex_endpoint() -> None:
    respx.get(
        "http://remote.test/users/0/items",
        params={"q": "ref", "qmode": "titleCreatorYear", "limit": 100, "start": 0},
    ).mock(
        return_value=Response(
            200,
            json=[
                {"key": "K1", "data": {"itemType": "journalArticle", "title": "First"}},
                {"key": "K2", "data": {"itemType": "journalArticle", "title": "Second"}},
            ],
        )
    )
    respx.get("http://remote.test/users/0/items", params={"itemKey": "K1,K2", "format": "bibtex"}).mock(
        return_value=Response(200, text="@article{firstRef,}\n\n@article{secondRef,}")
    )

    runner = CliRunner()
    result = invoke_remote(
        runner,
        [
            "--output",
            "bibtex",
            "search",
            "run",
            "ref",
            "--search-mode",
            "keyword",
            "--limit",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert "@article{firstRef" in result.output
    assert "@article{secondRef" in result.output


def test_item_get_bibtex_rejects_csl_flags() -> None:
    runner = CliRunner()
    result = invoke_remote(
        runner,
        [
            "--output",
            "bibtex",
            "item",
            "get",
            "XVMVWQZX",
            "--style",
            "apa",
        ],
    )

    assert result.exit_code != 0
    assert "only supported with --output bib" in result.output


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
