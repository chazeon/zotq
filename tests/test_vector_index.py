from __future__ import annotations

from pathlib import Path

import pytest

from zotq.models import VectorRecord
from zotq.storage import VectorIndex


def _vector(chunk_id: str, item_key: str, ordinal: int, embedding: list[float]) -> VectorRecord:
    return VectorRecord(chunk_id=chunk_id, item_key=item_key, ordinal=ordinal, embedding=embedding)


def test_vector_index_persists_and_ranks_by_similarity(tmp_path: Path) -> None:
    db_path = tmp_path / "vector.sqlite3"
    index = VectorIndex(db_path)
    try:
        index.upsert_item(
            "ITEM-A",
            [
                _vector("ITEM-A:0", "ITEM-A", 0, [1.0, 0.0]),
                _vector("ITEM-A:1", "ITEM-A", 1, [0.8, 0.2]),
            ],
        )
        index.upsert_item(
            "ITEM-B",
            [
                _vector("ITEM-B:0", "ITEM-B", 0, [0.0, 1.0]),
            ],
        )
    finally:
        index.close()

    reopened = VectorIndex(db_path)
    try:
        hits = reopened.search(query_vector=[1.0, 0.0], limit=5, offset=0)
        assert hits[0][0] == "ITEM-A"
        assert hits[0][1] > hits[1][1]
        assert reopened.document_count() == 2
        assert reopened.chunk_count() == 3
    finally:
        reopened.close()


def test_vector_index_rejects_dimension_mismatch(tmp_path: Path) -> None:
    index = VectorIndex(tmp_path / "vector.sqlite3")
    try:
        index.upsert_item("ITEM-A", [_vector("ITEM-A:0", "ITEM-A", 0, [1.0, 0.0, 0.0])])
        with pytest.raises(ValueError):
            index.upsert_item("ITEM-B", [_vector("ITEM-B:0", "ITEM-B", 0, [1.0, 0.0])])
    finally:
        index.close()


def test_vector_index_can_filter_allowed_item_keys(tmp_path: Path) -> None:
    index = VectorIndex(tmp_path / "vector.sqlite3")
    try:
        index.upsert_item("ITEM-A", [_vector("ITEM-A:0", "ITEM-A", 0, [1.0, 0.0])])
        index.upsert_item("ITEM-B", [_vector("ITEM-B:0", "ITEM-B", 0, [0.0, 1.0])])

        hits = index.search(query_vector=[1.0, 0.0], limit=5, allowed_item_keys={"ITEM-B"})

        assert [item_key for item_key, _ in hits] == ["ITEM-B"]
    finally:
        index.close()
