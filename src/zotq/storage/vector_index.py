"""SQLite-backed vector index with pluggable backend implementation."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Protocol

from ..models import VectorBackend, VectorRecord

try:
    import sqlite_vec
except Exception:  # pragma: no cover - optional runtime import guard
    sqlite_vec = None


class _VectorIndexBackend(Protocol):
    def upsert_item(self, item_key: str, vectors: list[VectorRecord]) -> None: ...

    def clear(self) -> None: ...

    def document_count(self) -> int: ...

    def chunk_count(self) -> int: ...

    def has_item(self, item_key: str) -> bool: ...

    def search(
        self,
        query_vector: list[float],
        *,
        limit: int,
        offset: int = 0,
        allowed_item_keys: set[str] | None = None,
    ) -> list[tuple[str, float]]: ...

    def migration_report(self) -> dict[str, object]: ...

    def close(self) -> None: ...


class _PythonVectorIndex:
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
        norm = _PythonVectorIndex._l2_norm(vector)
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

    def migration_report(self) -> dict[str, object]:
        return {
            "backend": VectorBackend.PYTHON.value,
            "performed": False,
            "legacy_rows": 0,
            "migrated_rows": 0,
        }


class _SqliteVecVectorIndex:
    """sqlite-vec accelerated backend."""

    def __init__(self, db_path: Path) -> None:
        if sqlite_vec is None:
            raise RuntimeError("sqlite-vec backend is unavailable: sqlite_vec module is not installed.")

        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._migration: dict[str, object] = {
            "backend": VectorBackend.SQLITE_VEC.value,
            "performed": False,
            "legacy_rows": 0,
            "migrated_rows": 0,
        }
        self._init_meta()
        self._migrate_legacy_python_rows_if_needed()
        expected = self._expected_dim()
        if expected is not None and not self._table_exists("vectors"):
            self._ensure_vectors_table(expected)

    def _init_meta(self) -> None:
        self._conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS vector_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

    def _table_exists(self, name: str = "vectors") -> bool:
        row = self._conn.execute(
            "SELECT 1 AS ok FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        return row is not None

    def _table_columns(self, name: str) -> list[str]:
        rows = self._conn.execute(f"PRAGMA table_info({name})").fetchall()
        return [str(row["name"]) for row in rows]

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

    def _is_legacy_python_vectors_table(self) -> bool:
        if not self._table_exists("vectors"):
            return False
        columns = set(self._table_columns("vectors"))
        return {"chunk_id", "item_key", "ordinal", "embedding_json", "norm"}.issubset(columns)

    def _parse_legacy_rows(self) -> tuple[list[tuple[str, str, int, list[float]]], int | None]:
        rows = self._conn.execute(
            "SELECT chunk_id, item_key, ordinal, embedding_json FROM vectors ORDER BY item_key, ordinal"
        ).fetchall()
        parsed: list[tuple[str, str, int, list[float]]] = []
        dim: int | None = None
        for row in rows:
            chunk_id = str(row["chunk_id"])
            item_key = str(row["item_key"])
            ordinal = int(row["ordinal"])
            try:
                raw_embedding = json.loads(str(row["embedding_json"]))
            except json.JSONDecodeError as exc:
                raise ValueError("Legacy vector row contains invalid embedding_json.") from exc
            if not isinstance(raw_embedding, list) or not raw_embedding:
                raise ValueError("Legacy vector row contains an empty or non-list embedding.")
            embedding = [float(value) for value in raw_embedding]
            if dim is None:
                dim = len(embedding)
            elif len(embedding) != dim:
                raise ValueError(f"Legacy vector dimension mismatch: expected {dim}, got {len(embedding)}.")
            parsed.append((chunk_id, item_key, ordinal, embedding))
        return parsed, dim

    def _migrate_legacy_python_rows_if_needed(self) -> None:
        if not self._is_legacy_python_vectors_table():
            return

        parsed_rows, detected_dim = self._parse_legacy_rows()
        legacy_rows = len(parsed_rows)
        self._migration["legacy_rows"] = legacy_rows

        expected_dim = self._expected_dim()
        if expected_dim is not None and detected_dim is not None and expected_dim != detected_dim:
            raise ValueError(f"Legacy vector dimension mismatch: expected {expected_dim}, got {detected_dim}.")
        if detected_dim is None:
            detected_dim = expected_dim

        with self._conn:
            if self._table_exists("vectors_legacy_python"):
                self._conn.execute("DROP TABLE vectors_legacy_python")
            self._conn.execute("ALTER TABLE vectors RENAME TO vectors_legacy_python")

            if detected_dim is not None:
                self._set_expected_dim(detected_dim)
                self._ensure_vectors_table(detected_dim)
                for chunk_id, item_key, ordinal, embedding in parsed_rows:
                    self._conn.execute(
                        "INSERT INTO vectors(chunk_id, embedding, item_key, ordinal) VALUES (?, ?, ?, ?)",
                        (chunk_id, json.dumps(embedding), item_key, ordinal),
                    )

            self._conn.execute("DROP TABLE vectors_legacy_python")

        self._migration["performed"] = True
        self._migration["migrated_rows"] = legacy_rows

    def _ensure_vectors_table(self, dim: int) -> None:
        if self._table_exists("vectors"):
            return
        self._conn.execute(
            f"""
            CREATE VIRTUAL TABLE vectors USING vec0(
                chunk_id text primary key,
                embedding float[{dim}] distance_metric=cosine,
                item_key text,
                ordinal int
            );
            """
        )

    def upsert_item(self, item_key: str, vectors: list[VectorRecord]) -> None:
        if not vectors:
            if self._table_exists("vectors"):
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
            self._ensure_vectors_table(expected_dim)
            self._conn.execute("DELETE FROM vectors WHERE item_key = ?", (item_key,))
            for record in vectors:
                if record.item_key != item_key:
                    raise ValueError("VectorRecord.item_key must match upsert item_key.")
                if len(record.embedding) != expected_dim:
                    raise ValueError(f"Vector dimension mismatch: expected {expected_dim}, got {len(record.embedding)}.")
                self._conn.execute(
                    "INSERT INTO vectors(chunk_id, embedding, item_key, ordinal) VALUES (?, ?, ?, ?)",
                    (record.chunk_id, json.dumps(record.embedding), item_key, record.ordinal),
                )

    def clear(self) -> None:
        with self._conn:
            if self._table_exists("vectors"):
                self._conn.execute("DROP TABLE vectors")
            self._conn.execute("DELETE FROM vector_meta")

    def document_count(self) -> int:
        if not self._table_exists("vectors"):
            return 0
        row = self._conn.execute("SELECT COUNT(DISTINCT item_key) AS c FROM vectors").fetchone()
        return int(row["c"]) if row else 0

    def chunk_count(self) -> int:
        if not self._table_exists("vectors"):
            return 0
        row = self._conn.execute("SELECT COUNT(*) AS c FROM vectors").fetchone()
        return int(row["c"]) if row else 0

    def has_item(self, item_key: str) -> bool:
        if not self._table_exists("vectors"):
            return False
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM vectors WHERE item_key = ?",
            (item_key,),
        ).fetchone()
        return bool(row and int(row["c"]) > 0)

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
        if not self._table_exists("vectors"):
            return []

        expected_dim = self._expected_dim()
        if expected_dim is None:
            return []
        if len(query_vector) != expected_dim:
            raise ValueError(f"Query vector dimension mismatch: expected {expected_dim}, got {len(query_vector)}.")

        if allowed_item_keys is not None and not allowed_item_keys:
            return []

        candidate_limit = max(1, self.chunk_count())
        where = "embedding MATCH ?"
        params: list[object] = [json.dumps(query_vector)]
        if allowed_item_keys is not None:
            ordered = sorted(allowed_item_keys)
            placeholders = ",".join("?" for _ in ordered)
            where += f" AND item_key IN ({placeholders})"
            params.extend(ordered)

        rows = self._conn.execute(
            f"SELECT item_key, distance FROM vectors WHERE {where} ORDER BY distance LIMIT ?",
            (*params, candidate_limit),
        ).fetchall()

        best_by_item: dict[str, float] = {}
        for row in rows:
            item_key = str(row["item_key"])
            distance = float(row["distance"])
            similarity = 1.0 - distance
            prev = best_by_item.get(item_key)
            if prev is None or similarity > prev:
                best_by_item[item_key] = similarity

        ranked = sorted(best_by_item.items(), key=lambda pair: (-pair[1], pair[0]))
        return ranked[offset : offset + limit]

    def close(self) -> None:
        self._conn.close()

    def migration_report(self) -> dict[str, object]:
        return dict(self._migration)


class VectorIndex:
    """Vector index facade supporting multiple backend implementations."""

    def __init__(self, db_path: Path, *, backend: VectorBackend = VectorBackend.PYTHON) -> None:
        if backend == VectorBackend.SQLITE_VEC:
            self._backend: _VectorIndexBackend = _SqliteVecVectorIndex(db_path)
        else:
            self._backend = _PythonVectorIndex(db_path)

    def upsert_item(self, item_key: str, vectors: list[VectorRecord]) -> None:
        self._backend.upsert_item(item_key, vectors)

    def clear(self) -> None:
        self._backend.clear()

    def document_count(self) -> int:
        return self._backend.document_count()

    def chunk_count(self) -> int:
        return self._backend.chunk_count()

    def has_item(self, item_key: str) -> bool:
        return self._backend.has_item(item_key)

    def search(
        self,
        query_vector: list[float],
        *,
        limit: int,
        offset: int = 0,
        allowed_item_keys: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        return self._backend.search(
            query_vector,
            limit=limit,
            offset=offset,
            allowed_item_keys=allowed_item_keys,
        )

    def close(self) -> None:
        self._backend.close()

    def migration_report(self) -> dict[str, object]:
        return self._backend.migration_report()
