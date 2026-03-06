from __future__ import annotations

from pathlib import Path

from zotq.index_service import MockIndexService
from zotq.models import IndexConfig, Item, QuerySpec, SearchHit, SearchMode


def _build_service(tmp_path: Path) -> MockIndexService:
    cfg = IndexConfig(
        enabled=True,
        index_dir=str(tmp_path / "index"),
        embedding_provider="local",
        embedding_model="hash-test",
    )
    return MockIndexService(cfg)


def test_hybrid_uses_normalized_signal_scores(tmp_path: Path, monkeypatch) -> None:
    service = _build_service(tmp_path)
    try:
        item_a = Item(key="A", item_type="journalArticle", title="Exact lexical match")
        item_b = Item(key="B", item_type="journalArticle", title="Strong semantic match")

        lexical_hits = [
            SearchHit(item=item_a, score=100.0, score_breakdown={"keyword": 100.0}),
            SearchHit(item=item_b, score=50.0, score_breakdown={"keyword": 50.0}),
        ]
        vector_hits = [
            ("A", 0.1),
            ("B", 0.9),
        ]

        monkeypatch.setattr(service._lexical, "search_keyword", lambda _: lexical_hits)  # type: ignore[attr-defined]
        monkeypatch.setattr(service._vector, "search", lambda *_args, **_kwargs: vector_hits)  # type: ignore[attr-defined]
        monkeypatch.setattr(service._vector, "chunk_count", lambda: 2)  # type: ignore[attr-defined]

        def fake_get_item(item_key: str) -> Item | None:
            if item_key == "A":
                return item_a
            if item_key == "B":
                return item_b
            return None

        monkeypatch.setattr(service._lexical, "get_item", fake_get_item)  # type: ignore[attr-defined]

        hits = service._search_hybrid(  # noqa: SLF001 - explicit behavior test for calibration policy
            QuerySpec(
                text="mantle hydration",
                search_mode=SearchMode.HYBRID,
                alpha=0.25,
                limit=2,
                offset=0,
            )
        )

        assert [hit.item.key for hit in hits] == ["B", "A"]
        assert hits[0].score_breakdown["lexical_raw"] == 50.0
        assert hits[0].score_breakdown["vector_raw"] == 0.9
        assert 0.0 <= hits[0].score_breakdown["lexical"] <= 1.0
        assert 0.0 <= hits[0].score_breakdown["vector"] <= 1.0
    finally:
        service.close()
