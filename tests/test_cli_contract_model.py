from __future__ import annotations

from zotq.contracts import build_cli_api_contract
from zotq.models import (
    ItemCiteKeyMultiKeyResponse,
    ItemCiteKeyPerKeyResult,
    ItemGetMultiKeyResponse,
    ItemGetPerKeyResult,
    MultiKeyResultStatus,
)


def test_v1_command_contract_contains_expected_commands() -> None:
    contract = build_cli_api_contract()
    names = contract.command_names()

    assert "system health" in names
    assert "search run" in names
    assert "item get" in names
    assert "item citekey" in names
    assert "collection list" in names
    assert "collection export" in names
    assert "tag list" in names
    assert "index status" in names
    assert "index inspect" in names
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


def test_multi_key_output_contracts_are_explicit() -> None:
    contract = build_cli_api_contract()
    by_command = {spec.command: spec for spec in contract.planned_output_contracts}

    get_spec = by_command["item get"]
    citekey_spec = by_command["item citekey"]

    assert get_spec.cli_form == "zotq item get --key K1 --key K2 ..."
    assert citekey_spec.cli_form == "zotq item citekey --key K1 --key K2 ... [--prefer ...]"
    assert get_spec.telemetry_fields == ["batch_used", "fallback_loop"]
    assert citekey_spec.telemetry_fields == ["batch_used", "fallback_loop"]
    assert get_spec.partial_failures_are_per_key is True
    assert citekey_spec.partial_failures_are_per_key is True


def test_multi_key_response_models_capture_partial_failures() -> None:
    get_payload = ItemGetMultiKeyResponse(
        results=[
            ItemGetPerKeyResult(key="K1", found=True, status=MultiKeyResultStatus.OK),
            ItemGetPerKeyResult(key="K2", found=False, status=MultiKeyResultStatus.NOT_FOUND),
            ItemGetPerKeyResult(key="K3", found=False, status=MultiKeyResultStatus.ERROR, error="timeout"),
        ]
    )
    citekey_payload = ItemCiteKeyMultiKeyResponse(
        results=[
            ItemCiteKeyPerKeyResult(
                key="K1",
                found=True,
                citation_key="alpha2026",
                status=MultiKeyResultStatus.OK,
                source="bibtex",
            ),
            ItemCiteKeyPerKeyResult(key="K2", found=False, status=MultiKeyResultStatus.NOT_FOUND),
        ]
    )

    assert [entry.status for entry in get_payload.results] == [
        MultiKeyResultStatus.OK,
        MultiKeyResultStatus.NOT_FOUND,
        MultiKeyResultStatus.ERROR,
    ]
    assert citekey_payload.results[0].citation_key == "alpha2026"
