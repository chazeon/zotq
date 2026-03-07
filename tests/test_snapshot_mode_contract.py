from __future__ import annotations

from zotq.contracts import build_cli_api_contract


def test_mode_global_option_includes_snapshot() -> None:
    contract = build_cli_api_contract()
    assert "--mode [local-api|remote|snapshot]" in contract.global_options


def test_snapshot_mode_does_not_change_command_grammar() -> None:
    contract = build_cli_api_contract()
    assert contract.grammar == "zotq <resource> <verb> [options]"
