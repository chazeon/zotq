"""Typed exceptions for CLI and service layers."""


class ZotQueryError(Exception):
    """Base exception type for zotq."""


class ConfigError(ZotQueryError):
    """Raised when configuration is invalid or missing."""


class BackendConnectionError(ZotQueryError):
    """Raised when backend communication fails."""


class QueryValidationError(ZotQueryError):
    """Raised when user query options are invalid."""


class ModeNotSupportedError(ZotQueryError):
    """Raised when the requested mode is unsupported."""


class IndexNotReadyError(ZotQueryError):
    """Raised when index-backed operations run before index readiness."""


class ExtractionError(ZotQueryError):
    """Raised when content extraction fails."""
