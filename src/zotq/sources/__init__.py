"""Source adapters."""

from .base import SourceAdapter, WatermarkSourceAdapter
from .local_api import LocalApiSourceAdapter
from .mock import MockSourceAdapter
from .remote_api import RemoteApiSourceAdapter
from .snapshot_bibtex import BibtexSnapshotSourceAdapter

__all__ = [
    "SourceAdapter",
    "WatermarkSourceAdapter",
    "LocalApiSourceAdapter",
    "RemoteApiSourceAdapter",
    "BibtexSnapshotSourceAdapter",
    "MockSourceAdapter",
]
