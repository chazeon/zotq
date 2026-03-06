"""Query mode resolution and fallback policy."""

from __future__ import annotations

from .errors import ModeNotSupportedError
from .models import BackendCapabilities, SearchMode


class QueryEngine:
    """Policy-only query engine helper for mode resolution in v1."""

    @staticmethod
    def resolve_execution_mode(
        requested: SearchMode,
        capabilities: BackendCapabilities,
        allow_fallback: bool,
    ) -> SearchMode:
        supported = {
            SearchMode.KEYWORD: capabilities.keyword,
            SearchMode.FUZZY: capabilities.fuzzy,
            SearchMode.SEMANTIC: capabilities.semantic,
            SearchMode.HYBRID: capabilities.hybrid,
        }

        if supported.get(requested, False):
            return requested

        if allow_fallback and capabilities.keyword:
            return SearchMode.KEYWORD

        raise ModeNotSupportedError(f"Search mode not supported: {requested.value}")
