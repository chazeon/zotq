from __future__ import annotations

from zotq.contracts import build_cli_api_contract


def test_v1_command_contract_contains_expected_commands() -> None:
    contract = build_cli_api_contract()
    names = contract.command_names()

    assert "system health" in names
    assert "search run" in names
    assert "item get" in names
    assert "item citekey" in names
    assert "collection list" in names
    assert "tag list" in names
    assert "index status" in names
    assert "index sync" in names
    assert "index rebuild" in names
    assert "index enrich" in names


def test_reserved_write_space_is_modeled_for_future() -> None:
    contract = build_cli_api_contract()
    reserved = contract.reserved_names()

    assert "collection add-item" in reserved
    assert "collection remove-item" in reserved
    assert "item create" in reserved
    assert "item delete" in reserved
    assert "tag add" in reserved
    assert "tag remove" in reserved


def test_global_options_are_explicit() -> None:
    contract = build_cli_api_contract()

    assert "-c, --config PATH" in contract.global_options
    assert "--mode [local-api|remote]" in contract.global_options
    assert "--output [table|json|jsonl|bib|bibtex]" in contract.global_options
