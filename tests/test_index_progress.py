from __future__ import annotations

import tempfile

from zotq.cli import RuntimeContext, _run_with_index_progress
from zotq.client import ZotQueryClient
from zotq.index_service import MockIndexService, RetrievalBenchmarkHarness
from zotq.models import AppConfig, IndexConfig, Item, OutputFormat, SearchDefaultsConfig
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
    assert any(event[0] == "enrich" for event in events)
    collect_events = [event for event in events if event[0] == "collect"]
    assert collect_events
    assert collect_events[-1] == ("collect", 4, 4)
    enrich_events = [event for event in events if event[0] == "enrich"]
    assert enrich_events
    assert enrich_events[0][1] == 0
    assert enrich_events[-1][2] is not None
    assert enrich_events[-1][1] == enrich_events[-1][2]
    assert events[-1][0] == "enrich"


def test_retrieval_benchmark_harness_tracks_stage_timings() -> None:
    ticks = iter([0.0, 0.01, 0.03, 0.05, 0.08, 0.12])
    harness = RetrievalBenchmarkHarness(now_fn=lambda: next(ticks))

    harness.observe("collect", 1, 4)
    harness.observe("collect", 4, 4)
    harness.observe("index", 2, 4)
    summary = harness.finish()

    assert summary["total_ms"] == 80
    assert summary["stage_order"] == ["collect", "index"]
    assert summary["stages"]["collect"]["events"] == 2
    assert summary["stages"]["collect"]["current"] == 4
    assert summary["stages"]["collect"]["total"] == 4
    assert summary["stages"]["collect"]["elapsed_ms"] == 40
    assert summary["stages"]["index"]["events"] == 1
    assert summary["stages"]["index"]["elapsed_ms"] == 30


def test_cli_progress_wrapper_returns_benchmark_payload_when_progress_hidden() -> None:
    runtime = RuntimeContext(
        config=AppConfig(),
        client=None,  # type: ignore[arg-type]
        output=OutputFormat.JSON,
        search_defaults=SearchDefaultsConfig(),
        verbose=False,
    )

    status, benchmark = _run_with_index_progress(
        runtime,
        "sync",
        lambda progress: _simulate_sync_progress(progress),
    )

    assert status == {"ok": True}
    assert benchmark["total_ms"] >= 0
    assert benchmark["stage_order"] == ["collect", "index", "enrich"]
    assert benchmark["stages"]["collect"]["events"] == 1
    assert benchmark["stages"]["index"]["events"] == 1
    assert benchmark["stages"]["enrich"]["events"] == 1


def _simulate_sync_progress(progress) -> dict[str, bool]:
    assert progress is not None
    progress("collect", 2, 4)
    progress("index", 1, 4)
    progress("enrich", 1, 1)
    return {"ok": True}
