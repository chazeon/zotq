"""SQLite-backed lexical index with FTS5."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import sqlite3
from typing import ClassVar
from difflib import SequenceMatcher
from pathlib import Path

from ..models import ChunkRecord, Item, QuerySpec, SearchHit


@dataclass(frozen=True)
class StructuredFieldDef:
    name: str
    item_attr: str
    normalizer: str = "text"
    identifier_type: str | None = None


class LexicalIndex:
    """Persistent lexical index built on SQLite + FTS5."""

    _STRUCTURED_FIELDS: ClassVar[tuple[StructuredFieldDef, ...]] = (
        StructuredFieldDef(name="doi", item_attr="doi", normalizer="doi", identifier_type="doi"),
        StructuredFieldDef(
            name="citation_key",
            item_attr="citation_key",
            normalizer="citation_key",
            identifier_type="citation_key",
        ),
        StructuredFieldDef(name="journal", item_attr="journal", normalizer="journal"),
        StructuredFieldDef(name="journal_abbreviation", item_attr="journal_abbreviation", normalizer="journal"),
        StructuredFieldDef(name="issn", item_attr="issn", normalizer="text"),
        StructuredFieldDef(name="volume", item_attr="volume", normalizer="text"),
        StructuredFieldDef(name="pages", item_attr="pages", normalizer="text"),
        StructuredFieldDef(name="language", item_attr="language", normalizer="text"),
    )

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

            CREATE TABLE IF NOT EXISTS documents (
                item_key TEXT PRIMARY KEY,
                item_json TEXT NOT NULL,
                title TEXT,
                item_type TEXT,
                date TEXT,
                creators TEXT,
                tags TEXT,
                full_text TEXT,
                content_hash TEXT,
                lexical_hash TEXT,
                vector_hash TEXT,
                lexical_profile_version INTEGER,
                vector_profile_version INTEGER,
                doi_norm TEXT,
                citation_key_norm TEXT,
                journal_norm TEXT
            );

            CREATE TABLE IF NOT EXISTS items (
                item_key TEXT PRIMARY KEY,
                item_type TEXT,
                title TEXT,
                date TEXT,
                doi_norm TEXT,
                raw_json TEXT NOT NULL,
                lexical_hash TEXT,
                vector_hash TEXT,
                content_hash TEXT,
                lexical_profile_version INTEGER,
                vector_profile_version INTEGER,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                item_key TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                text TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                chunk_id UNINDEXED,
                item_key UNINDEXED,
                text,
                tokenize='unicode61'
            );

            CREATE TABLE IF NOT EXISTS item_fields (
                item_key TEXT NOT NULL,
                field_name TEXT NOT NULL,
                ordinal INTEGER NOT NULL DEFAULT 0,
                value_raw TEXT,
                value_norm TEXT,
                value_hash TEXT NOT NULL,
                PRIMARY KEY (item_key, field_name, ordinal)
            );

            CREATE TABLE IF NOT EXISTS identifiers (
                id_type TEXT NOT NULL,
                id_norm TEXT NOT NULL,
                item_key TEXT NOT NULL,
                PRIMARY KEY (id_type, id_norm, item_key)
            );

            CREATE TABLE IF NOT EXISTS item_creators (
                item_key TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                creator_type TEXT,
                family TEXT,
                given TEXT,
                full_norm TEXT,
                key_norm TEXT,
                PRIMARY KEY (item_key, ordinal)
            );

            CREATE TABLE IF NOT EXISTS lexical_docs (
                item_key TEXT PRIMARY KEY,
                title TEXT,
                abstract TEXT,
                journal TEXT,
                creators TEXT,
                tags TEXT,
                body TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS lexical_fts USING fts5(
                item_key UNINDEXED,
                title,
                abstract,
                journal,
                creators,
                tags,
                body,
                tokenize='unicode61 remove_diacritics 2'
            );
            """
        )
        self._ensure_documents_columns()
        self._ensure_items_table()
        self._ensure_structured_tables()

    def _ensure_documents_columns(self) -> None:
        rows = self._conn.execute("PRAGMA table_info(documents)").fetchall()
        columns = {str(row["name"]) for row in rows}
        normalized_changed = False
        with self._conn:
            if "content_hash" not in columns:
                self._conn.execute("ALTER TABLE documents ADD COLUMN content_hash TEXT")
            if "lexical_hash" not in columns:
                self._conn.execute("ALTER TABLE documents ADD COLUMN lexical_hash TEXT")
            if "vector_hash" not in columns:
                self._conn.execute("ALTER TABLE documents ADD COLUMN vector_hash TEXT")
            if "lexical_profile_version" not in columns:
                self._conn.execute("ALTER TABLE documents ADD COLUMN lexical_profile_version INTEGER")
            if "vector_profile_version" not in columns:
                self._conn.execute("ALTER TABLE documents ADD COLUMN vector_profile_version INTEGER")
            if "doi_norm" not in columns:
                self._conn.execute("ALTER TABLE documents ADD COLUMN doi_norm TEXT")
                normalized_changed = True
            if "citation_key_norm" not in columns:
                self._conn.execute("ALTER TABLE documents ADD COLUMN citation_key_norm TEXT")
                normalized_changed = True
            if "journal_norm" not in columns:
                self._conn.execute("ALTER TABLE documents ADD COLUMN journal_norm TEXT")
                normalized_changed = True

            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_doi_norm ON documents(doi_norm)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_documents_citation_key_norm ON documents(citation_key_norm)"
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_journal_norm ON documents(journal_norm)")

        if normalized_changed:
            self._backfill_normalized_columns()

    def _ensure_structured_tables(self) -> None:
        with self._conn:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_item_fields_name_norm ON item_fields(field_name, value_norm, item_key)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_identifiers_type_norm ON identifiers(id_type, id_norm, item_key)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_item_creators_key_norm ON item_creators(key_norm, item_key, ordinal)"
            )
        self._backfill_structured_tables()
        self._backfill_creator_rows()
        self._backfill_lexical_projection()

    def _ensure_items_table(self) -> None:
        with self._conn:
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_items_doi_norm ON items(doi_norm)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_items_lexical_profile_version ON items(lexical_profile_version)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_items_vector_profile_version ON items(vector_profile_version)")
        self._backfill_items_table()

    @staticmethod
    def _field_value_hash(raw_value: str, normalized_value: str) -> str:
        payload = f"{raw_value}\u001f{normalized_value}"
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _structured_field_defs(cls) -> tuple[StructuredFieldDef, ...]:
        return cls._STRUCTURED_FIELDS

    @classmethod
    def _structured_field_names(cls) -> tuple[str, ...]:
        return tuple(field.name for field in cls._structured_field_defs())

    @classmethod
    def _structured_field_def(cls, field_name: str) -> StructuredFieldDef:
        for field in cls._structured_field_defs():
            if field.name == field_name:
                return field
        raise ValueError(f"Unsupported field for structured inspection: {field_name}")

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        return " ".join((value or "").strip().lower().split())

    @classmethod
    def _normalize_for_field(cls, field: StructuredFieldDef, value: str | None) -> str:
        if field.normalizer == "doi":
            return cls._normalize_doi(value)
        if field.normalizer == "citation_key":
            return cls._normalize_citation_key(value)
        if field.normalizer == "journal":
            return cls._normalize_journal(value)
        return cls._normalize_text(value)

    def _upsert_structured_rows(self, item: Item) -> None:
        field_norm_values: dict[str, str] = {}
        field_raw_values: dict[str, str] = {}
        for field in self._structured_field_defs():
            raw_value = str(getattr(item, field.item_attr) or "").strip()
            field_raw_values[field.name] = raw_value
            field_norm_values[field.name] = self._normalize_for_field(field, raw_value)

        with self._conn:
            for field in self._structured_field_defs():
                raw_value = field_raw_values[field.name]
                norm_value = field_norm_values[field.name]
                self._conn.execute(
                    """
                    INSERT INTO item_fields(item_key, field_name, ordinal, value_raw, value_norm, value_hash)
                    VALUES (?, ?, 0, ?, ?, ?)
                    ON CONFLICT(item_key, field_name, ordinal) DO UPDATE SET
                        value_raw=excluded.value_raw,
                        value_norm=excluded.value_norm,
                        value_hash=excluded.value_hash
                    """,
                    (item.key, field.name, raw_value, norm_value, self._field_value_hash(raw_value, norm_value)),
                )

            identifier_fields = [field for field in self._structured_field_defs() if field.identifier_type]
            if identifier_fields:
                placeholders = ",".join("?" for _ in identifier_fields)
                params: list[object] = [item.key]
                params.extend(field.identifier_type for field in identifier_fields if field.identifier_type)
                self._conn.execute(
                    f"DELETE FROM identifiers WHERE item_key = ? AND id_type IN ({placeholders})",
                    tuple(params),
                )

            for field in identifier_fields:
                if not field.identifier_type:
                    continue
                norm_value = field_norm_values[field.name]
                if not norm_value:
                    continue
                self._conn.execute(
                    "INSERT OR IGNORE INTO identifiers(id_type, id_norm, item_key) VALUES (?, ?, ?)",
                    (field.identifier_type, norm_value, item.key),
                )

    def _upsert_creator_rows(self, item: Item) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM item_creators WHERE item_key = ?", (item.key,))
            for ordinal, creator in enumerate(item.creators):
                family = (creator.last_name or "").strip()
                given = (creator.first_name or "").strip()
                full = " ".join(part for part in [given, family] if part).strip()
                key_norm = self._normalize_text(" ".join(part for part in [family, given] if part))
                self._conn.execute(
                    """
                    INSERT INTO item_creators(
                        item_key, ordinal, creator_type, family, given, full_norm, key_norm
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.key,
                        ordinal,
                        creator.creator_type,
                        family,
                        given,
                        self._normalize_text(full),
                        key_norm,
                    ),
                )

    def _upsert_lexical_projection(self, item: Item, *, full_text: str) -> None:
        creators_blob = self._creators_blob(item)
        tags_blob = ", ".join(item.tags)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO lexical_docs(item_key, title, abstract, journal, creators, tags, body)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_key) DO UPDATE SET
                    title=excluded.title,
                    abstract=excluded.abstract,
                    journal=excluded.journal,
                    creators=excluded.creators,
                    tags=excluded.tags,
                    body=excluded.body
                """,
                (
                    item.key,
                    item.title or "",
                    item.abstract or "",
                    item.journal or "",
                    creators_blob,
                    tags_blob,
                    full_text or "",
                ),
            )
            self._conn.execute("DELETE FROM lexical_fts WHERE item_key = ?", (item.key,))
            self._conn.execute(
                """
                INSERT INTO lexical_fts(item_key, title, abstract, journal, creators, tags, body)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.key,
                    item.title or "",
                    item.abstract or "",
                    item.journal or "",
                    creators_blob,
                    tags_blob,
                    full_text or "",
                ),
            )

    def _backfill_structured_tables(self) -> None:
        field_names = self._structured_field_names()
        if not field_names:
            return
        placeholders = ",".join("?" for _ in field_names)
        params: tuple[object, ...] = tuple(field_names) + (len(field_names),)
        rows = self._conn.execute(
            f"""
            SELECT d.item_key, d.item_json
            FROM documents d
            WHERE (
                SELECT COUNT(*)
                FROM item_fields f
                WHERE f.item_key = d.item_key
                  AND f.field_name IN ({placeholders})
                  AND f.ordinal = 0
            ) < ?
            ORDER BY d.item_key
            """,
            params,
        ).fetchall()
        if not rows:
            return

        for row in rows:
            try:
                item = Item.model_validate_json(str(row["item_json"] or ""))
            except Exception:
                continue
            self._upsert_structured_rows(item)

    def _backfill_creator_rows(self) -> None:
        rows = self._conn.execute(
            """
            SELECT d.item_key, d.item_json
            FROM documents d
            LEFT JOIN item_creators c
              ON c.item_key = d.item_key
            WHERE c.item_key IS NULL
            ORDER BY d.item_key
            """
        ).fetchall()
        if not rows:
            return
        for row in rows:
            try:
                item = Item.model_validate_json(str(row["item_json"] or ""))
            except Exception:
                continue
            self._upsert_creator_rows(item)

    def _backfill_lexical_projection(self) -> None:
        rows = self._conn.execute(
            """
            SELECT d.item_key, d.item_json, d.full_text
            FROM documents d
            LEFT JOIN lexical_docs ld
              ON ld.item_key = d.item_key
            WHERE ld.item_key IS NULL
            ORDER BY d.item_key
            """
        ).fetchall()
        if not rows:
            return
        for row in rows:
            try:
                item = Item.model_validate_json(str(row["item_json"] or ""))
            except Exception:
                continue
            full_text = str(row["full_text"] or "")
            self._upsert_lexical_projection(item, full_text=full_text)

    def _backfill_items_table(self) -> None:
        rows = self._conn.execute(
            """
            SELECT d.item_key, d.item_json, d.item_type, d.title, d.date, d.doi_norm, d.lexical_hash, d.vector_hash,
                   d.content_hash, d.lexical_profile_version, d.vector_profile_version
            FROM documents d
            LEFT JOIN items i
              ON i.item_key = d.item_key
            WHERE i.item_key IS NULL
            ORDER BY d.item_key
            """
        ).fetchall()
        if not rows:
            return

        with self._conn:
            for row in rows:
                self._conn.execute(
                    """
                    INSERT INTO items(
                        item_key, item_type, title, date, doi_norm, raw_json,
                        lexical_hash, vector_hash, content_hash, lexical_profile_version, vector_profile_version, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(item_key) DO UPDATE SET
                        item_type=excluded.item_type,
                        title=excluded.title,
                        date=excluded.date,
                        doi_norm=excluded.doi_norm,
                        raw_json=excluded.raw_json,
                        lexical_hash=excluded.lexical_hash,
                        vector_hash=excluded.vector_hash,
                        content_hash=excluded.content_hash,
                        lexical_profile_version=excluded.lexical_profile_version,
                        vector_profile_version=excluded.vector_profile_version,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        str(row["item_key"]),
                        row["item_type"],
                        row["title"],
                        row["date"],
                        row["doi_norm"],
                        str(row["item_json"] or "{}"),
                        row["lexical_hash"],
                        row["vector_hash"],
                        row["content_hash"],
                        row["lexical_profile_version"],
                        row["vector_profile_version"],
                    ),
                )

    def _backfill_normalized_columns(self) -> None:
        rows = self._conn.execute(
            """
            SELECT item_key, item_json
            FROM documents
            WHERE doi_norm IS NULL OR citation_key_norm IS NULL OR journal_norm IS NULL
            """
        ).fetchall()
        if not rows:
            return

        with self._conn:
            for row in rows:
                item_key = str(row["item_key"])
                item_json = str(row["item_json"] or "")
                doi = ""
                citation_key = ""
                journal = ""

                try:
                    item = Item.model_validate_json(item_json)
                    doi = self._normalize_doi(item.doi)
                    citation_key = self._normalize_citation_key(item.citation_key)
                    journal = self._normalize_journal(item.journal)
                except Exception:
                    try:
                        payload = json.loads(item_json)
                    except Exception:
                        payload = {}
                    if isinstance(payload, dict):
                        doi = self._normalize_doi(payload.get("doi"))  # type: ignore[arg-type]
                        citation_key = self._normalize_citation_key(payload.get("citation_key"))  # type: ignore[arg-type]
                        journal = self._normalize_journal(payload.get("journal"))  # type: ignore[arg-type]

                self._conn.execute(
                    """
                    UPDATE documents
                    SET doi_norm = ?, citation_key_norm = ?, journal_norm = ?
                    WHERE item_key = ?
                    """,
                    (doi, citation_key, journal, item_key),
                )

    @staticmethod
    def _creators_blob(item: Item) -> str:
        return "; ".join(
            " ".join(part for part in [creator.first_name, creator.last_name] if part).strip()
            for creator in item.creators
        )

    def upsert_item(
        self,
        item: Item,
        chunks: list[ChunkRecord],
        full_text: str,
        *,
        content_hash: str | None = None,
        lexical_hash: str | None = None,
        vector_hash: str | None = None,
        lexical_profile_version: int | None = None,
        vector_profile_version: int | None = None,
    ) -> None:
        item_json = item.model_dump_json()
        creators_blob = self._creators_blob(item)
        tags_blob = ",".join(item.tags)
        doi_norm = self._normalize_doi(item.doi)
        citation_key_norm = self._normalize_citation_key(item.citation_key)
        journal_norm = self._normalize_journal(item.journal)

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO items(
                    item_key, item_type, title, date, doi_norm, raw_json,
                    lexical_hash, vector_hash, content_hash, lexical_profile_version, vector_profile_version, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(item_key) DO UPDATE SET
                    item_type=excluded.item_type,
                    title=excluded.title,
                    date=excluded.date,
                    doi_norm=excluded.doi_norm,
                    raw_json=excluded.raw_json,
                    lexical_hash=excluded.lexical_hash,
                    vector_hash=excluded.vector_hash,
                    content_hash=excluded.content_hash,
                    lexical_profile_version=excluded.lexical_profile_version,
                    vector_profile_version=excluded.vector_profile_version,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    item.key,
                    item.item_type,
                    item.title,
                    item.date,
                    doi_norm,
                    item_json,
                    lexical_hash,
                    vector_hash,
                    content_hash,
                    lexical_profile_version,
                    vector_profile_version,
                ),
            )
            self._conn.execute(
                """
                INSERT INTO documents(
                    item_key, item_json, title, item_type, date, creators, tags, full_text,
                    content_hash, lexical_hash, vector_hash, lexical_profile_version, vector_profile_version,
                    doi_norm, citation_key_norm, journal_norm
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_key) DO UPDATE SET
                    item_json=excluded.item_json,
                    title=excluded.title,
                    item_type=excluded.item_type,
                    date=excluded.date,
                    creators=excluded.creators,
                    tags=excluded.tags,
                    full_text=excluded.full_text,
                    content_hash=excluded.content_hash,
                    lexical_hash=excluded.lexical_hash,
                    vector_hash=excluded.vector_hash,
                    lexical_profile_version=excluded.lexical_profile_version,
                    vector_profile_version=excluded.vector_profile_version,
                    doi_norm=excluded.doi_norm,
                    citation_key_norm=excluded.citation_key_norm,
                    journal_norm=excluded.journal_norm
                """,
                (
                    item.key,
                    item_json,
                    item.title,
                    item.item_type,
                    item.date,
                    creators_blob,
                    tags_blob,
                    full_text,
                    content_hash,
                    lexical_hash,
                    vector_hash,
                    lexical_profile_version,
                    vector_profile_version,
                    doi_norm,
                    citation_key_norm,
                    journal_norm,
                ),
            )

            self._conn.execute("DELETE FROM chunks WHERE item_key = ?", (item.key,))
            self._conn.execute("DELETE FROM chunks_fts WHERE item_key = ?", (item.key,))

            for chunk in chunks:
                self._conn.execute(
                    "INSERT INTO chunks(chunk_id, item_key, ordinal, text) VALUES (?, ?, ?, ?)",
                    (chunk.chunk_id, chunk.item_key, chunk.ordinal, chunk.text),
                )
                self._conn.execute(
                    "INSERT INTO chunks_fts(chunk_id, item_key, text) VALUES (?, ?, ?)",
                    (chunk.chunk_id, chunk.item_key, chunk.text),
                )
        self._upsert_structured_rows(item)
        self._upsert_creator_rows(item)
        self._upsert_lexical_projection(item, full_text=full_text)

    def clear(self) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM lexical_fts")
            self._conn.execute("DELETE FROM lexical_docs")
            self._conn.execute("DELETE FROM chunks_fts")
            self._conn.execute("DELETE FROM chunks")
            self._conn.execute("DELETE FROM item_creators")
            self._conn.execute("DELETE FROM identifiers")
            self._conn.execute("DELETE FROM item_fields")
            self._conn.execute("DELETE FROM documents")
            self._conn.execute("DELETE FROM items")

    def document_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()
        return int(row["c"]) if row else 0

    def chunk_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()
        return int(row["c"]) if row else 0

    def get_item(self, item_key: str) -> Item | None:
        row = self._conn.execute("SELECT raw_json FROM items WHERE item_key = ?", (item_key,)).fetchone()
        if row is not None:
            return Item.model_validate_json(row["raw_json"])
        fallback = self._conn.execute("SELECT item_json FROM documents WHERE item_key = ?", (item_key,)).fetchone()
        if fallback is None:
            return None
        return Item.model_validate_json(fallback["item_json"])

    def list_item_keys_missing_citation_key(self) -> list[str]:
        return self.list_item_keys_missing_field("citation_key")

    @classmethod
    def _normalize_field_name(cls, field: str) -> str:
        normalized = field.strip().lower()
        if normalized not in set(cls._structured_field_names()):
            raise ValueError(f"Unsupported field for structured inspection: {field}")
        return normalized

    def list_item_keys_missing_field(self, field: str, *, limit: int | None = None) -> list[str]:
        field_name = self._normalize_field_name(field)
        sql = """
            SELECT i.item_key
            FROM items i
            LEFT JOIN item_fields f
              ON f.item_key = i.item_key
             AND f.field_name = ?
             AND f.ordinal = 0
            WHERE COALESCE(f.value_norm, '') = ''
            ORDER BY i.item_key
        """
        params_list: list[object] = [field_name]
        params: tuple[object, ...] = ()
        if limit is not None:
            sql += "\nLIMIT ?"
            params_list.append(max(0, limit))
        params = tuple(params_list)
        rows = self._conn.execute(sql, params).fetchall()
        return [str(row["item_key"]) for row in rows]

    def count_missing_field(self, field: str) -> int:
        field_name = self._normalize_field_name(field)
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM items i
            LEFT JOIN item_fields f
              ON f.item_key = i.item_key
             AND f.field_name = ?
             AND f.ordinal = 0
            WHERE COALESCE(f.value_norm, '') = ''
            """
            ,
            (field_name,),
        ).fetchone()
        return int(row["c"]) if row else 0

    def count_profile_version_mismatches(self, column: str, target_version: int) -> int:
        if column not in {"lexical_profile_version", "vector_profile_version"}:
            raise ValueError(f"Unsupported profile version column: {column}")
        row = self._conn.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM items
            WHERE {column} IS NULL OR {column} != ?
            """,
            (int(target_version),),
        ).fetchone()
        return int(row["c"]) if row else 0

    def list_item_keys_with_profile_mismatch(
        self,
        column: str,
        target_version: int,
        *,
        limit: int | None = None,
    ) -> list[str]:
        if column not in {"lexical_profile_version", "vector_profile_version"}:
            raise ValueError(f"Unsupported profile version column: {column}")
        sql = f"""
            SELECT item_key
            FROM items
            WHERE {column} IS NULL OR {column} != ?
            ORDER BY item_key
        """
        params_list: list[object] = [int(target_version)]
        if limit is not None:
            sql += "\nLIMIT ?"
            params_list.append(max(0, limit))
        rows = self._conn.execute(sql, tuple(params_list)).fetchall()
        return [str(row["item_key"]) for row in rows]

    def inspect_structured_fields(
        self,
        *,
        sample_limit: int = 5,
        lexical_profile_version: int | None = None,
        vector_profile_version: int | None = None,
    ) -> dict[str, object]:
        doc_count = self.document_count()
        fields = list(self._structured_field_names())
        details: dict[str, object] = {}
        for field in fields:
            missing = self.count_missing_field(field)
            present = max(0, doc_count - missing)
            details[field] = {
                "missing": missing,
                "present": present,
                "sample_missing_item_keys": self.list_item_keys_missing_field(field, limit=sample_limit),
            }
        summary: dict[str, object] = {
            "documents": doc_count,
            "storage": "item_fields_v2",
            "fields": details,
        }
        profiles: dict[str, object] = {}
        if lexical_profile_version is not None:
            mismatched = self.count_profile_version_mismatches("lexical_profile_version", lexical_profile_version)
            profiles["lexical"] = {
                "target": lexical_profile_version,
                "matching": max(0, doc_count - mismatched),
                "mismatched": mismatched,
                "sample_mismatched_item_keys": self.list_item_keys_with_profile_mismatch(
                    "lexical_profile_version",
                    lexical_profile_version,
                    limit=sample_limit,
                ),
            }
        if vector_profile_version is not None:
            mismatched = self.count_profile_version_mismatches("vector_profile_version", vector_profile_version)
            profiles["vector"] = {
                "target": vector_profile_version,
                "matching": max(0, doc_count - mismatched),
                "mismatched": mismatched,
                "sample_mismatched_item_keys": self.list_item_keys_with_profile_mismatch(
                    "vector_profile_version",
                    vector_profile_version,
                    limit=sample_limit,
                ),
            }
        if profiles:
            summary["profiles"] = profiles
        return summary

    def set_item_citation_key(self, item_key: str, citation_key: str) -> bool:
        return self.set_item_structured_fields(item_key, citation_key=citation_key)

    def set_item_structured_fields(
        self,
        item_key: str,
        *,
        doi: str | None = None,
        citation_key: str | None = None,
        journal: str | None = None,
    ) -> bool:
        row = self._conn.execute("SELECT raw_json FROM items WHERE item_key = ?", (item_key,)).fetchone()
        raw_json = row["raw_json"] if row is not None else None
        if raw_json is None:
            fallback = self._conn.execute("SELECT item_json FROM documents WHERE item_key = ?", (item_key,)).fetchone()
            if fallback is not None:
                raw_json = fallback["item_json"]
        if raw_json is None:
            return False
        item = Item.model_validate_json(str(raw_json))
        changed = False

        if doi is not None:
            clean_doi = doi.strip()
            if clean_doi and clean_doi != (item.doi or ""):
                item.doi = clean_doi
                changed = True

        if citation_key is not None:
            clean_citation_key = citation_key.strip()
            if clean_citation_key and clean_citation_key != (item.citation_key or ""):
                item.citation_key = clean_citation_key
                changed = True

        if journal is not None:
            clean_journal = journal.strip()
            if clean_journal and clean_journal != (item.journal or ""):
                item.journal = clean_journal
                changed = True

        if not changed:
            return False

        with self._conn:
            self._conn.execute(
                """
                UPDATE items
                SET raw_json = ?, doi_norm = ?, title = ?, item_type = ?, date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE item_key = ?
                """,
                (
                    item.model_dump_json(),
                    self._normalize_doi(item.doi),
                    item.title,
                    item.item_type,
                    item.date,
                    item_key,
                ),
            )
            self._conn.execute(
                """
                UPDATE documents
                SET item_json = ?, doi_norm = ?, citation_key_norm = ?, journal_norm = ?
                WHERE item_key = ?
                """,
                (
                    item.model_dump_json(),
                    self._normalize_doi(item.doi),
                    self._normalize_citation_key(item.citation_key),
                    self._normalize_journal(item.journal),
                    item_key,
                ),
            )
        self._upsert_structured_rows(item)
        return True

    def get_content_hash(self, item_key: str) -> str | None:
        row = self._conn.execute("SELECT content_hash FROM items WHERE item_key = ?", (item_key,)).fetchone()
        if row is None:
            row = self._conn.execute("SELECT content_hash FROM documents WHERE item_key = ?", (item_key,)).fetchone()
        if row is None:
            return None
        value = row["content_hash"]
        return str(value) if value else None

    def get_item_hashes(self, item_key: str) -> tuple[str | None, str | None, str | None]:
        row = self._conn.execute(
            """
            SELECT lexical_hash, vector_hash, content_hash
            FROM items
            WHERE item_key = ?
            """,
            (item_key,),
        ).fetchone()
        if row is None:
            row = self._conn.execute(
                """
                SELECT lexical_hash, vector_hash, content_hash
                FROM documents
                WHERE item_key = ?
                """,
                (item_key,),
            ).fetchone()
        if row is None:
            return None, None, None
        lexical_hash = str(row["lexical_hash"]) if row["lexical_hash"] else None
        vector_hash = str(row["vector_hash"]) if row["vector_hash"] else None
        content_hash = str(row["content_hash"]) if row["content_hash"] else None
        return lexical_hash, vector_hash, content_hash

    def get_item_sync_state(self, item_key: str) -> tuple[str | None, str | None, str | None, int | None, int | None]:
        row = self._conn.execute(
            """
            SELECT lexical_hash, vector_hash, content_hash, lexical_profile_version, vector_profile_version
            FROM items
            WHERE item_key = ?
            """,
            (item_key,),
        ).fetchone()
        if row is None:
            row = self._conn.execute(
                """
                SELECT lexical_hash, vector_hash, content_hash, lexical_profile_version, vector_profile_version
                FROM documents
                WHERE item_key = ?
                """,
                (item_key,),
            ).fetchone()
        if row is None:
            return None, None, None, None, None

        lexical_hash = str(row["lexical_hash"]) if row["lexical_hash"] else None
        vector_hash = str(row["vector_hash"]) if row["vector_hash"] else None
        content_hash = str(row["content_hash"]) if row["content_hash"] else None
        lexical_profile_version = int(row["lexical_profile_version"]) if row["lexical_profile_version"] is not None else None
        vector_profile_version = int(row["vector_profile_version"]) if row["vector_profile_version"] is not None else None
        return lexical_hash, vector_hash, content_hash, lexical_profile_version, vector_profile_version

    def set_item_hashes(
        self,
        item_key: str,
        *,
        lexical_hash: str | None = None,
        vector_hash: str | None = None,
        content_hash: str | None = None,
        lexical_profile_version: int | None = None,
        vector_profile_version: int | None = None,
    ) -> bool:
        updates: list[str] = []
        params: list[object] = []
        if lexical_hash is not None:
            updates.append("lexical_hash = ?")
            params.append(lexical_hash)
        if vector_hash is not None:
            updates.append("vector_hash = ?")
            params.append(vector_hash)
        if content_hash is not None:
            updates.append("content_hash = ?")
            params.append(content_hash)
        if lexical_profile_version is not None:
            updates.append("lexical_profile_version = ?")
            params.append(int(lexical_profile_version))
        if vector_profile_version is not None:
            updates.append("vector_profile_version = ?")
            params.append(int(vector_profile_version))
        if not updates:
            return False

        params.append(item_key)
        with self._conn:
            cursor = self._conn.execute(
                f"UPDATE documents SET {', '.join(updates)} WHERE item_key = ?",
                tuple(params),
            )
            self._conn.execute(
                f"UPDATE items SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE item_key = ?",
                tuple(params),
            )
        return cursor.rowcount > 0

    def search_keyword(self, query: QuerySpec) -> list[SearchHit]:
        if not query.text:
            return self._search_by_filters_only(query, mode_name="keyword")

        filter_where, filter_params = self._structured_filter_sql(query, table_alias="documents")
        where_clauses = ["lexical_fts MATCH ?"]
        params: list[object] = [query.text]
        if filter_where:
            where_clauses.append(filter_where)
            params.extend(filter_params)
        where_sql = " AND ".join(where_clauses)

        cursor = self._conn.execute(
            f"""
            SELECT lexical_fts.item_key, bm25(lexical_fts, 0.0, 3.0, 1.6, 1.8, 1.2, 1.0, 0.9) AS score
            FROM lexical_fts
            JOIN documents ON documents.item_key = lexical_fts.item_key
            WHERE {where_sql}
            ORDER BY score
            LIMIT ?
            """,
            tuple(params + [max((query.limit + query.offset) * 20, 200)]),
        )
        rows = cursor.fetchall()

        best_by_item: dict[str, float | None] = {}
        for row in rows:
            item_key = row["item_key"]
            score = float(row["score"]) if row["score"] is not None else None
            best_by_item[item_key] = score

        ranked: list[tuple[float, bool, str, Item]] = []
        for key, raw_score in best_by_item.items():
            item = self.get_item(key)
            if not item:
                continue
            if not self._matches_filters(item, query):
                continue
            final_score = self._keyword_final_score(item, query, raw_score)
            ranked.append((final_score, self._is_attachment(item), item.key, item))

        ranked.sort(key=lambda t: (-t[0], t[1], t[2]))
        selected = ranked[query.offset : query.offset + query.limit]

        hits: list[SearchHit] = []
        for score, _, _, item in selected:
            hits.append(SearchHit(item=item, score=score, score_breakdown={"keyword": score}))
        return hits

    def search_fuzzy(self, query: QuerySpec) -> list[SearchHit]:
        if not query.text:
            return self._search_by_filters_only(query, mode_name="fuzzy")

        target = query.text.lower()
        filter_where, filter_params = self._structured_filter_sql(query, table_alias="documents")
        sql = """
            SELECT
                documents.item_json AS item_json,
                COALESCE(lexical_docs.title, documents.title, '') AS title,
                COALESCE(lexical_docs.body, documents.full_text, '') AS full_text
            FROM documents
            LEFT JOIN lexical_docs ON lexical_docs.item_key = documents.item_key
        """
        if filter_where:
            sql += f" WHERE {filter_where}"
        sql += " ORDER BY documents.item_key"
        rows = self._conn.execute(sql, tuple(filter_params)).fetchall()

        scored: list[tuple[float, bool, str, Item]] = []
        for row in rows:
            title = (row["title"] or "").lower()
            full_text = (row["full_text"] or "").lower()
            similarity = max(
                SequenceMatcher(None, target, title).ratio(),
                SequenceMatcher(None, target, full_text[:2000]).ratio(),
            )
            if target in title or target in full_text or similarity >= 0.45:
                item = Item.model_validate_json(row["item_json"])
                if not self._matches_filters(item, query):
                    continue
                score = self._fuzzy_final_score(item, query, similarity)
                scored.append((score, self._is_attachment(item), item.key, item))

        scored.sort(key=lambda x: (-x[0], x[1], x[2]))
        sliced = scored[query.offset : query.offset + query.limit]

        hits: list[SearchHit] = []
        for score, _, _, item in sliced:
            hits.append(SearchHit(item=item, score=score, score_breakdown={"fuzzy": score}))
        return hits

    @staticmethod
    def _is_attachment(item: Item) -> bool:
        return (item.item_type or "").lower() == "attachment"

    def _attachment_penalty(self, item: Item, query: QuerySpec) -> float:
        if query.item_type:
            return 1.0
        if self._is_attachment(item):
            return 0.35
        return 1.0

    @staticmethod
    def _title_bonus(item: Item, query: QuerySpec) -> float:
        if not query.text:
            return 0.0
        title = (item.title or "").lower()
        text = query.text.lower()
        if text == title:
            return 2.0
        if text in title:
            return 0.75
        return 0.0

    def _keyword_final_score(self, item: Item, query: QuerySpec, raw_score: float | None) -> float:
        # SQLite BM25 lower-is-better and can be negative. Normalize to higher-is-better.
        base = max(0.0, -(raw_score or 0.0))
        boosted = base + self._title_bonus(item, query)
        return boosted * self._attachment_penalty(item, query)

    def _fuzzy_final_score(self, item: Item, query: QuerySpec, similarity: float) -> float:
        boosted = similarity + (self._title_bonus(item, query) / 4.0)
        return boosted * self._attachment_penalty(item, query)

    @staticmethod
    def _extract_year(date_value: str | None) -> int | None:
        if not date_value:
            return None
        if len(date_value) >= 4 and date_value[:4].isdigit():
            return int(date_value[:4])
        return None

    @staticmethod
    def _normalize_doi(value: str | None) -> str:
        raw = (value or "").strip().lower()
        if raw.startswith("https://doi.org/"):
            raw = raw[len("https://doi.org/") :]
        if raw.startswith("http://doi.org/"):
            raw = raw[len("http://doi.org/") :]
        if raw.startswith("doi:"):
            raw = raw[4:]
        return raw.strip()

    @staticmethod
    def _normalize_citation_key(value: str | None) -> str:
        return (value or "").strip().lower()

    @staticmethod
    def _normalize_journal(value: str | None) -> str:
        return " ".join((value or "").strip().lower().split())

    @classmethod
    def _structured_filter_sql(
        cls,
        query: QuerySpec,
        *,
        table_alias: str = "",
    ) -> tuple[str, list[object]]:
        item_key_ref = f"{table_alias}.item_key" if table_alias else "item_key"
        clauses: list[str] = []
        params: list[object] = []

        doi_norm = cls._normalize_doi(query.doi)
        if doi_norm:
            clauses.append(
                f"EXISTS (SELECT 1 FROM identifiers i WHERE i.item_key = {item_key_ref} AND i.id_type = 'doi' AND i.id_norm = ?)"
            )
            params.append(doi_norm)

        citation_key_norm = cls._normalize_citation_key(query.citation_key)
        if citation_key_norm:
            clauses.append(
                f"EXISTS (SELECT 1 FROM identifiers i WHERE i.item_key = {item_key_ref} AND i.id_type = 'citation_key' AND i.id_norm = ?)"
            )
            params.append(citation_key_norm)

        journal_norm = cls._normalize_journal(query.journal)
        if journal_norm:
            clauses.append(
                f"EXISTS (SELECT 1 FROM item_fields f WHERE f.item_key = {item_key_ref} AND f.field_name = 'journal' AND f.value_norm LIKE ?)"
            )
            params.append(f"%{journal_norm}%")

        return " AND ".join(clauses), params

    def item_keys_for_structured_filters(self, query: QuerySpec) -> set[str] | None:
        where_sql, params = self._structured_filter_sql(query, table_alias="documents")
        if not where_sql:
            return None
        rows = self._conn.execute(
            f"SELECT item_key FROM documents WHERE {where_sql} ORDER BY item_key",
            tuple(params),
        ).fetchall()
        return {str(row["item_key"]) for row in rows}

    @classmethod
    def _matches_filters(cls, item: Item, query: QuerySpec) -> bool:
        if query.title and query.title.lower() not in (item.title or "").lower():
            return False
        if query.doi and cls._normalize_doi(query.doi) != cls._normalize_doi(item.doi):
            return False
        if query.journal and cls._normalize_journal(query.journal) not in cls._normalize_journal(item.journal):
            return False
        if query.citation_key and cls._normalize_citation_key(query.citation_key) != cls._normalize_citation_key(item.citation_key):
            return False
        if query.item_type and query.item_type != item.item_type:
            return False
        if query.tags:
            item_tags = {tag.lower() for tag in item.tags}
            if not all(tag.lower() in item_tags for tag in query.tags):
                return False
        if query.creators:
            creator_blob = " ".join(
                f"{creator.first_name or ''} {creator.last_name or ''}".strip().lower() for creator in item.creators
            )
            for creator in query.creators:
                if creator.lower() not in creator_blob:
                    return False
        year = cls._extract_year(item.date)
        if query.year_from is not None and year is not None and year < query.year_from:
            return False
        if query.year_to is not None and year is not None and year > query.year_to:
            return False
        return True

    def _search_by_filters_only(self, query: QuerySpec, *, mode_name: str) -> list[SearchHit]:
        filter_where, filter_params = self._structured_filter_sql(query)
        sql = "SELECT item_json FROM documents"
        if filter_where:
            sql += f" WHERE {filter_where}"
        sql += " ORDER BY item_key"
        rows = self._conn.execute(sql, tuple(filter_params)).fetchall()
        hits: list[SearchHit] = []
        for row in rows:
            item = Item.model_validate_json(row["item_json"])
            if not self._matches_filters(item, query):
                continue
            score = self._attachment_penalty(item, query)
            hits.append(SearchHit(item=item, score=score, score_breakdown={mode_name: score}))
        return hits[query.offset : query.offset + query.limit]

    def close(self) -> None:
        self._conn.close()
