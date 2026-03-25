from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from zotq.errors import ConfigError
from zotq.index_service import MockIndexService
from zotq.models import IndexConfig, VectorBackend, VectorRecord
from zotq.storage.vector_index import VectorIndex


def _vector(chunk_id: str, item_key: str, ordinal: int, embedding: list[float]) -> VectorRecord:
    return VectorRecord(chunk_id=chunk_id, item_key=item_key, ordinal=ordinal, embedding=embedding)


def _seed_python_backend(db_path: Path) -> None:
    index = VectorIndex(db_path, backend=VectorBackend.PYTHON)
    try:
        index.upsert_item(
            "ITEM-A",
            [
                _vector("ITEM-A:0", "ITEM-A", 0, [1.0, 0.0]),
                _vector("ITEM-A:1", "ITEM-A", 1, [0.8, 0.2]),
            ],
        )
        index.upsert_item("ITEM-B", [_vector("ITEM-B:0", "ITEM-B", 0, [0.0, 1.0])])
    finally:
        index.close()


def test_sqlite_vec_backfills_legacy_python_vectors(tmp_path: Path) -> None:
    db_path = tmp_path / "vector.sqlite3"
    _seed_python_backend(db_path)

    index = VectorIndex(db_path, backend=VectorBackend.SQLITE_VEC)
    try:
        migration = index.migration_report()
        assert migration["performed"] is True
        assert migration["migrated_rows"] == 3
        assert migration["legacy_rows"] == 3

        hits = index.search(query_vector=[1.0, 0.0], limit=10)
        assert hits[0][0] == "ITEM-A"
        assert index.document_count() == 2
        assert index.chunk_count() == 3
    finally:
        index.close()

    reopened = VectorIndex(db_path, backend=VectorBackend.SQLITE_VEC)
    try:
        migration = reopened.migration_report()
        assert migration["performed"] is False
        assert migration["legacy_rows"] == 0
        assert reopened.chunk_count() == 3
    finally:
        reopened.close()


def test_index_service_inspect_reports_vector_migration(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    _seed_python_backend(index_dir / "vector.sqlite3")

    cfg = IndexConfig(enabled=True, index_dir=str(index_dir), vector_backend=VectorBackend.SQLITE_VEC)
    service = MockIndexService(cfg)
    try:
        inspect = service.inspect_index()
        migration = inspect.get("vector_migration")
        assert isinstance(migration, dict)
        assert migration.get("performed") is True
        assert migration.get("migrated_rows") == 3
        assert inspect["vectors"] == 3
    finally:
        service.close()


def test_sqlite_vec_migration_rejects_legacy_dimension_mismatch(tmp_path: Path) -> None:
    db_path = tmp_path / "broken.sqlite3"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE vector_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE vectors (
                chunk_id TEXT PRIMARY KEY,
                item_key TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                embedding_json TEXT NOT NULL,
                norm REAL NOT NULL
            );
            """
        )
        conn.execute("INSERT INTO vectors VALUES (?, ?, ?, ?, ?)", ("K1:0", "K1", 0, "[1.0, 0.0]", 1.0))
        conn.execute("INSERT INTO vectors VALUES (?, ?, ?, ?, ?)", ("K2:0", "K2", 0, "[1.0, 0.0, 0.0]", 1.0))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="Legacy vector dimension mismatch"):
        idx = VectorIndex(db_path, backend=VectorBackend.SQLITE_VEC)
        idx.close()


def test_python_backend_rejects_sqlite_vec_vectors_table(tmp_path: Path) -> None:
    db_path = tmp_path / "vector.sqlite3"
    seeded = VectorIndex(db_path, backend=VectorBackend.SQLITE_VEC)
    try:
        seeded.upsert_item("ITEM-A", [_vector("ITEM-A:0", "ITEM-A", 0, [1.0, 0.0])])
    finally:
        seeded.close()

    with pytest.raises(ValueError, match="Vector backend mismatch"):
        VectorIndex(db_path, backend=VectorBackend.PYTHON)


def test_index_service_surfaces_backend_mismatch_as_config_error(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    db_path = index_dir / "vector.sqlite3"

    seeded = VectorIndex(db_path, backend=VectorBackend.SQLITE_VEC)
    try:
        seeded.upsert_item("ITEM-A", [_vector("ITEM-A:0", "ITEM-A", 0, [1.0, 0.0])])
    finally:
        seeded.close()

    cfg = IndexConfig(enabled=True, index_dir=str(index_dir), vector_backend=VectorBackend.PYTHON)
    with pytest.raises(ConfigError, match="Vector backend mismatch"):
        MockIndexService(cfg)
