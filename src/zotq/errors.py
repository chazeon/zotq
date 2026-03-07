"""Typed exceptions for CLI and service layers."""

from __future__ import annotations

from enum import Enum


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


class ErrorCode(str, Enum):
    CLI_USAGE = "cli_usage"
    CONFIG_ERROR = "config_error"
    BACKEND_ERROR = "backend_error"
    MODE_NOT_SUPPORTED = "mode_not_supported"
    INDEX_NOT_READY = "index_not_ready"
    PRECONDITION_FAILED = "precondition_failed"
    INTERNAL_ERROR = "internal_error"


def classify_error(exc: Exception) -> ErrorCode:
    if isinstance(exc, ConfigError):
        return ErrorCode.CONFIG_ERROR
    if isinstance(exc, BackendConnectionError):
        return ErrorCode.BACKEND_ERROR
    if isinstance(exc, ModeNotSupportedError):
        return ErrorCode.MODE_NOT_SUPPORTED
    if isinstance(exc, IndexNotReadyError):
        return ErrorCode.INDEX_NOT_READY
    if isinstance(exc, (QueryValidationError, ValueError)):
        return ErrorCode.CLI_USAGE
    return ErrorCode.INTERNAL_ERROR
