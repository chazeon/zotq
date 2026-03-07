from __future__ import annotations

from pathlib import Path

from zotq.models import VectorBackend, VectorRecord
from zotq.storage.vector_index import VectorIndex


def _vector(chunk_id: str, item_key: str, ordinal: int, embedding: list[float]) -> VectorRecord:
    return VectorRecord(chunk_id=chunk_id, item_key=item_key, ordinal=ordinal, embedding=embedding)


def _populate(index: VectorIndex) -> None:
    index.upsert_item(
        "ITEM-A",
        [
            _vector("ITEM-A:0", "ITEM-A", 0, [1.0, 0.0]),
            _vector("ITEM-A:1", "ITEM-A", 1, [0.9, 0.1]),
        ],
    )
    index.upsert_item("ITEM-B", [_vector("ITEM-B:0", "ITEM-B", 0, [0.0, 1.0])])


def test_sqlite_vec_backend_matches_python_backend_rankings(tmp_path: Path) -> None:
    py_index = VectorIndex(tmp_path / "python.sqlite3", backend=VectorBackend.PYTHON)
    vec_index = VectorIndex(tmp_path / "sqlite_vec.sqlite3", backend=VectorBackend.SQLITE_VEC)
    try:
        _populate(py_index)
        _populate(vec_index)

        py_hits = py_index.search(query_vector=[1.0, 0.0], limit=10)
        vec_hits = vec_index.search(query_vector=[1.0, 0.0], limit=10)

        assert [item_key for item_key, _ in py_hits] == [item_key for item_key, _ in vec_hits]
        assert py_index.document_count() == vec_index.document_count() == 2
        assert py_index.chunk_count() == vec_index.chunk_count() == 3
    finally:
        py_index.close()
        vec_index.close()


def test_sqlite_vec_backend_respects_allowed_item_keys(tmp_path: Path) -> None:
    index = VectorIndex(tmp_path / "sqlite_vec.sqlite3", backend=VectorBackend.SQLITE_VEC)
    try:
        _populate(index)
        hits = index.search(query_vector=[1.0, 0.0], limit=10, allowed_item_keys={"ITEM-B"})
        assert [item_key for item_key, _ in hits] == ["ITEM-B"]
    finally:
        index.close()
