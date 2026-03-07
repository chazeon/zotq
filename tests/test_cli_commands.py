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
def test_search_run_no_attachments_excludes_attachment_hits() -> None:
    respx.get("http://remote.test/users/0/items").mock(
        return_value=Response(
            200,
            json=[
                {
                    "key": "ARTICLE1",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Mantle hydration overview",
                        "date": "2015",
                    },
                },
                {
                    "key": "ATTACH1",
                    "data": {
                        "itemType": "attachment",
                        "title": "Mantle hydration PDF",
                        "date": "2015",
                    },
                },
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
            "mantle hydration",
            "--search-mode",
            "keyword",
            "--no-attachments",
            "--limit",
            "5",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["query"]["include_attachments"] is False
    hit_types = [hit["item"]["item_type"] for hit in payload["hits"]]
    assert "attachment" not in hit_types
    assert "journalArticle" in hit_types


@respx.mock
def test_search_run_attachments_flag_keeps_attachment_hits() -> None:
    respx.get("http://remote.test/users/0/items").mock(
        return_value=Response(
            200,
            json=[
                {
                    "key": "ARTICLE1",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Mantle hydration overview",
                        "date": "2015",
                    },
                },
                {
                    "key": "ATTACH1",
                    "data": {
                        "itemType": "attachment",
                        "title": "Mantle hydration PDF",
                        "date": "2015",
                    },
                },
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
            "mantle hydration",
            "--search-mode",
            "keyword",
            "--attachments",
            "--limit",
            "5",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["query"]["include_attachments"] is True
    hit_types = [hit["item"]["item_type"] for hit in payload["hits"]]
    assert "attachment" in hit_types


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
def test_item_citekey_supports_multi_key_option_json_output() -> None:
    respx.get("http://remote.test/users/0/items", params={"itemKey": "K1,MISSING"}).mock(
        return_value=Response(
            200,
            json=[
                {
                    "key": "K1",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "First Item",
                        "citationKey": "alpha2026",
                    },
                }
            ],
        )
    )

    runner = CliRunner()
    result = invoke_remote(
        runner,
        ["--output", "json", "item", "citekey", "--key", "K1", "--key", "MISSING"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["command"] == "item citekey"
    assert payload["results"][0]["key"] == "K1"
    assert payload["results"][0]["found"] is True
    assert payload["results"][0]["citation_key"] == "alpha2026"
    assert payload["results"][0]["status"] == "ok"
    assert payload["results"][1]["key"] == "MISSING"
    assert payload["results"][1]["found"] is False
    assert payload["results"][1]["status"] == "not_found"


def test_item_citekey_requires_positional_or_repeatable_key() -> None:
    runner = CliRunner()
    result = invoke_remote(runner, ["--output", "json", "item", "citekey"])

    assert result.exit_code != 0
    assert "Pass KEY or at least one --key value" in result.output


@respx.mock
def test_item_get_supports_multi_key_option_json_output() -> None:
    respx.get("http://remote.test/users/0/items", params={"itemKey": "K1,MISSING"}).mock(
        return_value=Response(
            200,
            json=[
                {
                    "key": "K1",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "First Item",
                    },
                }
            ],
        )
    )

    runner = CliRunner()
    result = invoke_remote(
        runner,
        ["--output", "json", "item", "get", "--key", "K1", "--key", "MISSING"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["command"] == "item get"
    assert payload["results"][0]["key"] == "K1"
    assert payload["results"][0]["found"] is True
    assert payload["results"][0]["status"] == "ok"
    assert payload["results"][1]["key"] == "MISSING"
    assert payload["results"][1]["found"] is False
    assert payload["results"][1]["status"] == "not_found"


@respx.mock
def test_item_get_single_key_shape_is_unchanged() -> None:
    respx.get("http://remote.test/users/0/items/K1").mock(
        return_value=Response(
            200,
            json={
                "key": "K1",
                "data": {
                    "itemType": "journalArticle",
                    "title": "First Item",
                },
            },
        )
    )

    runner = CliRunner()
    result = invoke_remote(runner, ["--output", "json", "item", "get", "K1"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["found"] is True
    assert payload["item"]["key"] == "K1"


def test_item_get_requires_positional_or_repeatable_key() -> None:
    runner = CliRunner()
    result = invoke_remote(runner, ["--output", "json", "item", "get"])

    assert result.exit_code != 0
    assert "Pass KEY or at least one --key value" in result.output


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


def test_collection_export_requires_bibtex_output() -> None:
    runner = CliRunner()
    result = invoke_remote(
        runner,
        [
            "--output",
            "json",
            "collection",
            "export",
            "C1",
            "--format",
            "bibtex",
        ],
    )

    assert result.exit_code != 0
    assert "requires --output bibtex" in result.output


@respx.mock
def test_collection_export_bibtex_paginates_and_batches() -> None:
    respx.get(
        "http://remote.test/users/0/collections/C1/items",
        params={"limit": 100, "start": 0},
    ).mock(
        return_value=Response(
            200,
            json=[
                {"key": "K1", "data": {"itemType": "journalArticle", "title": "First"}},
                {"key": "K2", "data": {"itemType": "journalArticle", "title": "Second"}},
            ],
        )
    )
    respx.get(
        "http://remote.test/users/0/collections/C1/items",
        params={"limit": 100, "start": 2},
    ).mock(
        return_value=Response(
            200,
            json=[
                {"key": "K3", "data": {"itemType": "journalArticle", "title": "Third"}},
            ],
        )
    )
    respx.get("http://remote.test/users/0/items", params={"itemKey": "K1,K2", "format": "bibtex"}).mock(
        return_value=Response(200, text="@article{k1,}\n\n@article{k2,}")
    )
    respx.get("http://remote.test/users/0/items", params={"itemKey": "K3", "format": "bibtex"}).mock(
        return_value=Response(200, text="@article{k3,}")
    )

    runner = CliRunner()
    result = invoke_remote(
        runner,
        [
            "--output",
            "bibtex",
            "collection",
            "export",
            "C1",
            "--format",
            "bibtex",
            "--batch-size",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert "@article{k1" in result.output
    assert "@article{k2" in result.output
    assert "@article{k3" in result.output


@respx.mock
def test_collection_export_include_children_traverses_descendants() -> None:
    respx.get("http://remote.test/users/0/collections").mock(
        return_value=Response(
            200,
            json=[
                {"key": "C1", "data": {"name": "Root", "parentCollection": None}},
                {"key": "C2", "data": {"name": "Child", "parentCollection": "C1"}},
                {"key": "C9", "data": {"name": "Other", "parentCollection": None}},
            ],
        )
    )
    respx.get(
        "http://remote.test/users/0/collections/C1/items",
        params={"limit": 100, "start": 0},
    ).mock(
        return_value=Response(
            200,
            json=[
                {"key": "K1", "data": {"itemType": "journalArticle", "title": "First"}},
            ],
        )
    )
    respx.get(
        "http://remote.test/users/0/collections/C2/items",
        params={"limit": 100, "start": 0},
    ).mock(
        return_value=Response(
            200,
            json=[
                {"key": "K1", "data": {"itemType": "journalArticle", "title": "First"}},
                {"key": "K2", "data": {"itemType": "journalArticle", "title": "Second"}},
            ],
        )
    )
    bib_route = respx.get("http://remote.test/users/0/items", params={"itemKey": "K1,K2", "format": "bibtex"}).mock(
        return_value=Response(200, text="@article{k1,}\n\n@article{k2,}")
    )

    runner = CliRunner()
    result = invoke_remote(
        runner,
        [
            "--output",
            "bibtex",
            "collection",
            "export",
            "C1",
            "--format",
            "bibtex",
            "--include-children",
            "--batch-size",
            "3",
        ],
    )

    assert result.exit_code == 0
    assert "@article{k1" in result.output
    assert "@article{k2" in result.output
    assert bib_route.called is True


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
    respx.get("http://remote.test/users/0/items", params={"itemKey": "MI26RYRR", "format": "bibtex"}).mock(
        return_value=Response(200, text="@article{nishiMantleHydration2015,}")
    )
    respx.get("http://remote.test/users/0/items/MI26RYRR", params={"format": "bibtex"}).mock(
        return_value=Response(200, text="@article{nishiMantleHydration2015,}")
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
    respx.get("http://remote.test/users/0/items", params={"itemKey": "MI26RYRR", "format": "bibtex"}).mock(
        return_value=Response(200, text="@article{nishiMantleHydration2015,}")
    )
    respx.get("http://remote.test/users/0/items/MI26RYRR", params={"format": "bibtex"}).mock(
        return_value=Response(200, text="@article{nishiMantleHydration2015,}")
    )

    runner = CliRunner()
    result = invoke_remote(runner, ["--output", "json", "index", "sync", "--full", "--progress"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["action"] == "sync"
    assert payload["status"]["ready"] is True


def test_index_sync_rejects_profiles_only_with_full() -> None:
    runner = CliRunner()
    result = invoke_remote(runner, ["--output", "json", "index", "sync", "--full", "--profiles-only"])

    assert result.exit_code != 0
    assert "--profiles-only cannot be combined with --full" in result.output


def test_index_enrich_returns_counts_when_index_empty() -> None:
    runner = CliRunner()
    result = invoke_remote(runner, ["--output", "json", "index", "enrich", "--no-progress"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["action"] == "enrich"
    assert payload["field"] == "citation-key"
    assert payload["results"]["citation-key"]["missing"] == 0
    assert payload["results"]["citation-key"]["updated"] == 0
    assert payload["results"]["citation-key"]["remaining"] == 0


def test_index_enrich_all_fields_when_index_empty() -> None:
    runner = CliRunner()
    result = invoke_remote(runner, ["--output", "json", "index", "enrich", "--field", "all", "--no-progress"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["action"] == "enrich"
    assert payload["field"] == "all"
    assert payload["results"]["citation-key"]["missing"] == 0
    assert payload["results"]["doi"]["missing"] == 0
    assert payload["results"]["journal"]["missing"] == 0


def test_index_inspect_returns_field_coverage_summary() -> None:
    runner = CliRunner()
    result = invoke_remote(runner, ["--output", "json", "index", "inspect", "--sample-limit", "2"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "documents" in payload
    assert "chunks" in payload
    assert "vectors" in payload
    assert "fields" in payload
    fields = payload["fields"]
    assert "doi" in fields
    assert "citation_key" in fields
    assert "journal" in fields
    assert isinstance(fields["doi"]["sample_missing_item_keys"], list)


def test_index_inspect_returns_profile_mismatch_summary() -> None:
    runner = CliRunner()
    result = invoke_remote(runner, ["--output", "json", "index", "inspect", "--sample-limit", "2"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "profiles" in payload
    assert payload["profiles"]["lexical"]["target"] == 1
    assert payload["profiles"]["vector"]["target"] == 1
    assert payload["profiles"]["lexical"]["mismatched"] == 0
    assert payload["profiles"]["vector"]["mismatched"] == 0
