from __future__ import annotations

from pathlib import Path

import pytest

from zotq.errors import IndexNotReadyError
from zotq.index_service import MockIndexService
from zotq.models import IndexConfig, Item


def test_index_status_persists_between_instances(tmp_path: Path) -> None:
    cfg = IndexConfig(index_dir=str(tmp_path / "index"), enabled=True, embedding_provider="local", embedding_model="test")

    service = MockIndexService(cfg)
    before = service.status()
    assert before.ready is False

    synced = service.sync(full=True, items=[Item(key="K1", title="One"), Item(key="K2", title="Two")])
    assert synced.ready is True
    assert synced.chunk_count >= 2

    reloaded = MockIndexService(cfg)
    status = reloaded.status()
    assert status.ready is True
    assert status.chunk_count >= 2
    assert status.document_count == 2


def test_index_sync_rebuild_fail_when_disabled(tmp_path: Path) -> None:
    cfg = IndexConfig(index_dir=str(tmp_path / "index"), enabled=False)
    service = MockIndexService(cfg)

    with pytest.raises(IndexNotReadyError):
        service.sync(full=False)

    with pytest.raises(IndexNotReadyError):
        service.rebuild()


def test_non_full_sync_skips_unchanged_items(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = IndexConfig(index_dir=str(tmp_path / "index"), enabled=True, embedding_provider="local", embedding_model="test")
    service = MockIndexService(cfg)
    try:
        calls = {"count": 0}
        original_embed_texts = service._embedding.embed_texts  # type: ignore[attr-defined]

        def counting_embed_texts(texts: list[str]) -> list[list[float]]:
            calls["count"] += 1
            return original_embed_texts(texts)

        monkeypatch.setattr(service._embedding, "embed_texts", counting_embed_texts)  # type: ignore[attr-defined]

        items = [Item(key="K1", title="One"), Item(key="K2", title="Two")]

        service.sync(full=True, items=items)
        first_calls = calls["count"]
        assert first_calls > 0

        service.sync(full=False, items=items)
        assert calls["count"] == first_calls

        changed = [Item(key="K1", title="One updated"), Item(key="K2", title="Two")]
        service.sync(full=False, items=changed)
        assert calls["count"] == first_calls + 1
    finally:
        service.close()


def test_non_full_sync_metadata_only_change_skips_reembed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = IndexConfig(index_dir=str(tmp_path / "index"), enabled=True, embedding_provider="local", embedding_model="test")
    service = MockIndexService(cfg)
    try:
        calls = {"count": 0}
        original_embed_texts = service._embedding.embed_texts  # type: ignore[attr-defined]

        def counting_embed_texts(texts: list[str]) -> list[list[float]]:
            calls["count"] += 1
            return original_embed_texts(texts)

        monkeypatch.setattr(service._embedding, "embed_texts", counting_embed_texts)  # type: ignore[attr-defined]

        initial = [Item(key="K1", title="One", journal="Journal A", doi="10.1000/a")]
        service.sync(full=True, items=initial)
        first_calls = calls["count"]
        assert first_calls > 0

        metadata_changed = [Item(key="K1", title="One", journal="Journal B", doi="10.1000/b")]
        service.sync(full=False, items=metadata_changed)
        assert calls["count"] == first_calls
    finally:
        service.close()


def test_non_full_sync_semantic_change_triggers_reembed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = IndexConfig(index_dir=str(tmp_path / "index"), enabled=True, embedding_provider="local", embedding_model="test")
    service = MockIndexService(cfg)
    try:
        calls = {"count": 0}
        original_embed_texts = service._embedding.embed_texts  # type: ignore[attr-defined]

        def counting_embed_texts(texts: list[str]) -> list[list[float]]:
            calls["count"] += 1
            return original_embed_texts(texts)

        monkeypatch.setattr(service._embedding, "embed_texts", counting_embed_texts)  # type: ignore[attr-defined]

        initial = [Item(key="K1", title="One", abstract="old abstract")]
        service.sync(full=True, items=initial)
        first_calls = calls["count"]
        assert first_calls > 0

        semantic_changed = [Item(key="K1", title="One", abstract="new abstract")]
        service.sync(full=False, items=semantic_changed)
        assert calls["count"] == first_calls + 1
    finally:
        service.close()


def test_full_sync_resumes_from_checkpoint_after_interruption(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = IndexConfig(index_dir=str(tmp_path / "index"), enabled=True, embedding_provider="local", embedding_model="test")
    items = [
        Item(key="K1", title="One"),
        Item(key="K2", title="Two"),
        Item(key="K3", title="Three"),
    ]

    service = MockIndexService(cfg)
    try:
        original_embed_texts = service._embedding.embed_texts  # type: ignore[attr-defined]
        calls = {"count": 0}

        def flaky_embed_texts(texts: list[str]) -> list[list[float]]:
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("interrupted")
            return original_embed_texts(texts)

        monkeypatch.setattr(service._embedding, "embed_texts", flaky_embed_texts)  # type: ignore[attr-defined]

        with pytest.raises(RuntimeError, match="interrupted"):
            service.sync(full=True, items=items)
    finally:
        service.close()

    resumed_service = MockIndexService(cfg)
    try:
        resumed_calls = {"count": 0}
        resumed_orig_embed = resumed_service._embedding.embed_texts  # type: ignore[attr-defined]
        events: list[tuple[str, int, int | None]] = []

        def counting_embed_texts(texts: list[str]) -> list[list[float]]:
            resumed_calls["count"] += 1
            return resumed_orig_embed(texts)

        monkeypatch.setattr(resumed_service._embedding, "embed_texts", counting_embed_texts)  # type: ignore[attr-defined]

        status = resumed_service.sync(
            full=True,
            items=items,
            progress=lambda phase, current, total: events.append((phase, current, total)),
        )

        assert status.ready is True
        assert resumed_calls["count"] == 2
        index_events = [event for event in events if event[0] == "index"]
        assert index_events
        assert index_events[0] == ("index", 2, 3)
        assert index_events[-1] == ("index", 3, 3)
        assert all(event[1] != 1 for event in index_events)

        payload = resumed_service._checkpoints.read()  # type: ignore[attr-defined]
        assert "ingest" not in payload
        assert "last_sync_at" in payload
    finally:
        resumed_service.close()


def test_vector_profile_version_bump_triggers_reembed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base_cfg = IndexConfig(
        index_dir=str(tmp_path / "index"),
        enabled=True,
        embedding_provider="local",
        embedding_model="test",
        lexical_profile_version=1,
        vector_profile_version=1,
    )
    items = [Item(key="K1", title="One", abstract="A")]

    service = MockIndexService(base_cfg)
    try:
        service.sync(full=True, items=items)
    finally:
        service.close()

    bumped_cfg = IndexConfig(
        index_dir=base_cfg.index_dir,
        enabled=True,
        embedding_provider="local",
        embedding_model="test",
        lexical_profile_version=1,
        vector_profile_version=2,
    )
    bumped = MockIndexService(bumped_cfg)
    try:
        calls = {"count": 0}
        original_embed_texts = bumped._embedding.embed_texts  # type: ignore[attr-defined]

        def counting_embed_texts(texts: list[str]) -> list[list[float]]:
            calls["count"] += 1
            return original_embed_texts(texts)

        monkeypatch.setattr(bumped._embedding, "embed_texts", counting_embed_texts)  # type: ignore[attr-defined]
        bumped.sync(full=False, items=items)
        assert calls["count"] == 1
    finally:
        bumped.close()


def test_lexical_profile_version_bump_skips_reembed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base_cfg = IndexConfig(
        index_dir=str(tmp_path / "index"),
        enabled=True,
        embedding_provider="local",
        embedding_model="test",
        lexical_profile_version=1,
        vector_profile_version=1,
    )
    items = [Item(key="K1", title="One", abstract="A")]

    service = MockIndexService(base_cfg)
    try:
        service.sync(full=True, items=items)
    finally:
        service.close()

    bumped_cfg = IndexConfig(
        index_dir=base_cfg.index_dir,
        enabled=True,
        embedding_provider="local",
        embedding_model="test",
        lexical_profile_version=2,
        vector_profile_version=1,
    )
    bumped = MockIndexService(bumped_cfg)
    try:
        calls = {"count": 0}
        original_embed_texts = bumped._embedding.embed_texts  # type: ignore[attr-defined]

        def counting_embed_texts(texts: list[str]) -> list[list[float]]:
            calls["count"] += 1
            return original_embed_texts(texts)

        monkeypatch.setattr(bumped._embedding, "embed_texts", counting_embed_texts)  # type: ignore[attr-defined]
        bumped.sync(full=False, items=items)
        assert calls["count"] == 0
    finally:
        bumped.close()
