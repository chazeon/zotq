from __future__ import annotations

from pathlib import Path

from zotq.index_service import MockIndexService
from zotq.models import IndexConfig, Item, QuerySpec, SearchMode


def _build_service(tmp_path: Path) -> MockIndexService:
    cfg = IndexConfig(
        enabled=True,
        index_dir=str(tmp_path / "index"),
        embedding_provider="local",
        embedding_model="hash-test",
    )
    return MockIndexService(cfg)


def test_capabilities_enable_semantic_after_index_is_ready(tmp_path: Path) -> None:
    service = _build_service(tmp_path)

    before = service.capabilities()
    assert before.semantic is False
    assert before.hybrid is False

    items = [
        Item(key="I1", item_type="journalArticle", title="Mantle hydration", abstract="Water in subduction zones."),
        Item(key="I2", item_type="journalArticle", title="Machine learning optimization", abstract="Neural training."),
    ]
    status = service.sync(full=True, items=items)
    assert status.ready is True

    after = service.capabilities()
    assert after.semantic is True
    assert after.hybrid is True


def test_semantic_search_returns_relevant_item_first(tmp_path: Path) -> None:
    service = _build_service(tmp_path)
    try:
        items = [
            Item(
                key="GEO-A",
                item_type="journalArticle",
                title="Mantle hydration and water storage",
                abstract="Hydrated mantle wedge and slab dehydration.",
            ),
            Item(
                key="ML-B",
                item_type="journalArticle",
                title="Bayesian optimization for machine learning",
                abstract="Acquisition functions for hyperparameter search.",
            ),
            Item(
                key="GEO-C",
                item_type="journalArticle",
                title="Hydrated mantle wedge dynamics",
                abstract="Water transport in subduction environments.",
            ),
        ]
        service.sync(full=True, items=items)

        hits = service.search(
            QuerySpec(text="mantle hydration", search_mode=SearchMode.SEMANTIC, limit=2, offset=0),
        )

        assert len(hits) == 2
        assert hits[0].item.key in {"GEO-A", "GEO-C"}
        assert hits[0].item.key != "ML-B"
        assert hits[0].score is not None
    finally:
        service.close()


def test_hybrid_search_prefers_exact_lexical_match(tmp_path: Path) -> None:
    service = _build_service(tmp_path)
    try:
        items = [
            Item(
                key="EXACT",
                item_type="journalArticle",
                title="mantle hydration",
                abstract="subduction zone water budget",
            ),
            Item(
                key="RELATED",
                item_type="journalArticle",
                title="Hydrated mantle wedge dynamics",
                abstract="water transport and devolatilization",
            ),
        ]
        service.sync(full=True, items=items)

        hits = service.search(
            QuerySpec(
                text="mantle hydration",
                search_mode=SearchMode.HYBRID,
                alpha=0.8,
                lexical_k=10,
                vector_k=10,
                limit=2,
                offset=0,
            )
        )

        assert len(hits) == 2
        assert hits[0].item.key == "EXACT"
        assert hits[0].score is not None
        assert hits[0].score_breakdown.get("hybrid") is not None
        assert hits[0].score_breakdown.get("lexical") is not None
        assert hits[0].score_breakdown.get("vector") is not None
    finally:
        service.close()


def test_semantic_downranks_attachments_by_default(tmp_path: Path) -> None:
    service = _build_service(tmp_path)
    try:
        items = [
            Item(
                key="ARTICLE",
                item_type="journalArticle",
                title="mantle hydration",
                abstract="mantle hydration",
            ),
            Item(
                key="ATTACH",
                item_type="attachment",
                title="mantle hydration.pdf",
                abstract="mantle hydration",
            ),
        ]
        service.sync(full=True, items=items)

        hits = service.search(
            QuerySpec(text="mantle hydration", search_mode=SearchMode.SEMANTIC, limit=2, offset=0),
        )

        assert [hit.item.key for hit in hits] == ["ARTICLE", "ATTACH"]
        assert hits[0].score is not None
        assert hits[1].score is not None
        assert hits[0].score > hits[1].score
    finally:
        service.close()
