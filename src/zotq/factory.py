"""Factory functions for adapters and services."""

from __future__ import annotations

from .index_service import MockIndexService
from .models import Mode, ProfileConfig
from .sources import BibtexSnapshotSourceAdapter, LocalApiSourceAdapter, RemoteApiSourceAdapter, SourceAdapter


def build_source_adapter(profile: ProfileConfig) -> SourceAdapter:
    if profile.mode == Mode.LOCAL_API:
        return LocalApiSourceAdapter(profile)
    if profile.mode == Mode.REMOTE:
        return RemoteApiSourceAdapter(profile)
    if profile.mode == Mode.SNAPSHOT:
        return BibtexSnapshotSourceAdapter(profile)
    raise ValueError(f"Unsupported mode: {profile.mode}")


def build_index_service(profile: ProfileConfig) -> MockIndexService:
    return MockIndexService(profile.index)
