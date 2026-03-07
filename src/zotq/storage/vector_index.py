"""SQLite-backed vector index for semantic retrieval."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

from ..models import VectorRecord


class VectorIndex:
    """Persistent vector storage with Python-level cosine retrieval."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS vector_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vectors (
                chunk_id TEXT PRIMARY KEY,
                item_key TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                embedding_json TEXT NOT NULL,
                norm REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_vectors_item_key ON vectors(item_key);
            """
        )

    @staticmethod
    def _l2_norm(vector: list[float]) -> float:
        return math.sqrt(sum(value * value for value in vector))

    @staticmethod
    def _normalize(vector: list[float]) -> tuple[list[float], float]:
        norm = VectorIndex._l2_norm(vector)
        if norm == 0.0:
            return [0.0] * len(vector), 0.0
        return [value / norm for value in vector], 1.0

    def _expected_dim(self) -> int | None:
        row = self._conn.execute("SELECT value FROM vector_meta WHERE key = 'dimension'").fetchone()
        if row is None:
            return None
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return None

    def _set_expected_dim(self, dim: int) -> None:
        self._conn.execute(
            """
            INSERT INTO vector_meta(key, value)
            VALUES ('dimension', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(dim),),
        )

    def upsert_item(self, item_key: str, vectors: list[VectorRecord]) -> None:
        if not vectors:
            with self._conn:
                self._conn.execute("DELETE FROM vectors WHERE item_key = ?", (item_key,))
            return

        dim = len(vectors[0].embedding)
        if dim == 0:
            raise ValueError("Vector dimension must be non-zero.")

        expected_dim = self._expected_dim()
        if expected_dim is None:
            expected_dim = dim
        if dim != expected_dim:
            raise ValueError(f"Vector dimension mismatch: expected {expected_dim}, got {dim}.")

        with self._conn:
            self._set_expected_dim(expected_dim)
            self._conn.execute("DELETE FROM vectors WHERE item_key = ?", (item_key,))
            for record in vectors:
                if record.item_key != item_key:
                    raise ValueError("VectorRecord.item_key must match upsert item_key.")
                if len(record.embedding) != expected_dim:
                    raise ValueError(f"Vector dimension mismatch: expected {expected_dim}, got {len(record.embedding)}.")

                normalized, norm = self._normalize(record.embedding)
                self._conn.execute(
                    """
                    INSERT INTO vectors(chunk_id, item_key, ordinal, embedding_json, norm)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (record.chunk_id, item_key, record.ordinal, json.dumps(normalized), norm),
                )

    def clear(self) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM vectors")
            self._conn.execute("DELETE FROM vector_meta")

    def document_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(DISTINCT item_key) AS c FROM vectors").fetchone()
        return int(row["c"]) if row else 0

    def chunk_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM vectors").fetchone()
        return int(row["c"]) if row else 0

    def has_item(self, item_key: str) -> bool:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM vectors WHERE item_key = ?",
            (item_key,),
        ).fetchone()
        return bool(row and int(row["c"]) > 0)

    @staticmethod
    def _dot(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    def search(
        self,
        query_vector: list[float],
        *,
        limit: int,
        offset: int = 0,
        allowed_item_keys: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        if not query_vector or limit <= 0:
            return []

        expected_dim = self._expected_dim()
        if expected_dim is None:
            return []
        if len(query_vector) != expected_dim:
            raise ValueError(f"Query vector dimension mismatch: expected {expected_dim}, got {len(query_vector)}.")

        normalized_query, query_norm = self._normalize(query_vector)
        if query_norm == 0.0:
            return []

        rows = self._conn.execute(
            "SELECT item_key, embedding_json, norm FROM vectors ORDER BY item_key, ordinal"
        ).fetchall()

        best_by_item: dict[str, float] = {}
        for row in rows:
            if float(row["norm"]) == 0.0:
                continue
            item_key = str(row["item_key"])
            if allowed_item_keys is not None and item_key not in allowed_item_keys:
                continue
            chunk_vector = json.loads(row["embedding_json"])
            similarity = self._dot(normalized_query, chunk_vector)
            prev = best_by_item.get(item_key)
            if prev is None or similarity > prev:
                best_by_item[item_key] = similarity

        ranked = sorted(best_by_item.items(), key=lambda pair: (-pair[1], pair[0]))
        return ranked[offset : offset + limit]

    def close(self) -> None:
        self._conn.close()
