from __future__ import annotations

import tempfile

from zotq.client import ZotQueryClient
from zotq.index_service import MockIndexService
from zotq.models import AppConfig, IndexConfig, Item
from zotq.sources.mock import MockSourceAdapter


def test_index_service_sync_reports_index_progress(tmp_path) -> None:
    cfg = IndexConfig(
        enabled=True,
        index_dir=str(tmp_path / "index"),
        embedding_provider="local",
        embedding_model="local-hash-v1",
    )
    service = MockIndexService(cfg)
    try:
        items = [
            Item(key="K1", title="One"),
            Item(key="K2", title="Two"),
            Item(key="K3", title="Three"),
        ]
        events: list[tuple[str, int, int | None]] = []

        status = service.sync(full=True, items=items, progress=lambda phase, current, total: events.append((phase, current, total)))

        assert status.ready is True
        assert events
        assert all(phase == "index" for phase, _, _ in events)
        assert events[-1] == ("index", 3, 3)
    finally:
        service.close()


def test_client_index_sync_reports_collect_and_index_progress() -> None:
    config = AppConfig()
    profile = config.profiles["default"]
    profile.index.enabled = True
    profile.index.index_dir = tempfile.mkdtemp(prefix="zotq-test-index-progress-")

    client = ZotQueryClient(
        config=config,
        profile_name="default",
        source_adapter=MockSourceAdapter(semantic_enabled=True),
        index_service=MockIndexService(profile.index),
    )

    events: list[tuple[str, int, int | None]] = []
    status = client.index_sync(full=True, progress=lambda phase, current, total: events.append((phase, current, total)))

    assert status.ready is True
    assert any(event[0] == "collect" for event in events)
    assert any(event[0] == "index" for event in events)
    collect_events = [event for event in events if event[0] == "collect"]
    assert collect_events
    assert collect_events[-1] == ("collect", 4, 4)
    assert events[-1][0] == "index"
