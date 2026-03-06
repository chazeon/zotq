from __future__ import annotations

import pytest
from pydantic import ValidationError

from zotq.errors import ModeNotSupportedError
from zotq.models import BackendCapabilities, QuerySpec, SearchMode
from zotq.query_engine import QueryEngine


def test_query_spec_numeric_bounds() -> None:
    with pytest.raises(ValidationError):
        QuerySpec(limit=0)

    with pytest.raises(ValidationError):
        QuerySpec(offset=-1)

    with pytest.raises(ValidationError):
        QuerySpec(alpha=1.5)


def test_requested_mode_runs_when_supported() -> None:
    capabilities = BackendCapabilities(keyword=True, fuzzy=True, semantic=True, hybrid=True)

    executed = QueryEngine.resolve_execution_mode(
        requested=SearchMode.SEMANTIC,
        capabilities=capabilities,
        allow_fallback=False,
    )

    assert executed == SearchMode.SEMANTIC


def test_unsupported_mode_falls_back_when_enabled() -> None:
    capabilities = BackendCapabilities(keyword=True, fuzzy=True, semantic=False, hybrid=False)

    executed = QueryEngine.resolve_execution_mode(
        requested=SearchMode.SEMANTIC,
        capabilities=capabilities,
        allow_fallback=True,
    )

    assert executed == SearchMode.KEYWORD


def test_unsupported_mode_errors_without_fallback() -> None:
    capabilities = BackendCapabilities(keyword=True, fuzzy=True, semantic=False, hybrid=False)

    with pytest.raises(ModeNotSupportedError):
        QueryEngine.resolve_execution_mode(
            requested=SearchMode.SEMANTIC,
            capabilities=capabilities,
            allow_fallback=False,
        )
