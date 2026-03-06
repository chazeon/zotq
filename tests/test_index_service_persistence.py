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
