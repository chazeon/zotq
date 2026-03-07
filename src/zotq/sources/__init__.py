"""Source adapters."""

from .base import SourceAdapter, WatermarkSourceAdapter
from .local_api import LocalApiSourceAdapter
from .mock import MockSourceAdapter
from .remote_api import RemoteApiSourceAdapter

__all__ = [
    "SourceAdapter",
    "WatermarkSourceAdapter",
    "LocalApiSourceAdapter",
    "RemoteApiSourceAdapter",
    "MockSourceAdapter",
]
