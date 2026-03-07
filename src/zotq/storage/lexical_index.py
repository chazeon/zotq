"""SQLite-backed lexical index with FTS5."""

from __future__ import annotations

import json
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

from ..models import ChunkRecord, Item, QuerySpec, SearchHit


class LexicalIndex:
    """Persistent lexical index built on SQLite + FTS5."""

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
                doi_norm TEXT,
                citation_key_norm TEXT,
                journal_norm TEXT
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
            """
        )
        self._ensure_documents_columns()

    def _ensure_documents_columns(self) -> None:
        rows = self._conn.execute("PRAGMA table_info(documents)").fetchall()
        columns = {str(row["name"]) for row in rows}
        changed = False
        with self._conn:
            if "content_hash" not in columns:
                self._conn.execute("ALTER TABLE documents ADD COLUMN content_hash TEXT")
                changed = True
            if "doi_norm" not in columns:
                self._conn.execute("ALTER TABLE documents ADD COLUMN doi_norm TEXT")
                changed = True
            if "citation_key_norm" not in columns:
                self._conn.execute("ALTER TABLE documents ADD COLUMN citation_key_norm TEXT")
                changed = True
            if "journal_norm" not in columns:
                self._conn.execute("ALTER TABLE documents ADD COLUMN journal_norm TEXT")
                changed = True

            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_doi_norm ON documents(doi_norm)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_documents_citation_key_norm ON documents(citation_key_norm)"
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_journal_norm ON documents(journal_norm)")

        if changed:
            self._backfill_normalized_columns()

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

    def upsert_item(self, item: Item, chunks: list[ChunkRecord], full_text: str, *, content_hash: str | None = None) -> None:
        item_json = item.model_dump_json()
        creators_blob = self._creators_blob(item)
        tags_blob = ",".join(item.tags)
        doi_norm = self._normalize_doi(item.doi)
        citation_key_norm = self._normalize_citation_key(item.citation_key)
        journal_norm = self._normalize_journal(item.journal)

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO documents(
                    item_key, item_json, title, item_type, date, creators, tags, full_text,
                    content_hash, doi_norm, citation_key_norm, journal_norm
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_key) DO UPDATE SET
                    item_json=excluded.item_json,
                    title=excluded.title,
                    item_type=excluded.item_type,
                    date=excluded.date,
                    creators=excluded.creators,
                    tags=excluded.tags,
                    full_text=excluded.full_text,
                    content_hash=excluded.content_hash,
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

    def clear(self) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM chunks_fts")
            self._conn.execute("DELETE FROM chunks")
            self._conn.execute("DELETE FROM documents")

    def document_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()
        return int(row["c"]) if row else 0

    def chunk_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()
        return int(row["c"]) if row else 0

    def get_item(self, item_key: str) -> Item | None:
        row = self._conn.execute("SELECT item_json FROM documents WHERE item_key = ?", (item_key,)).fetchone()
        if row is None:
            return None
        return Item.model_validate_json(row["item_json"])

    def list_item_keys_missing_citation_key(self) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT item_key
            FROM documents
            WHERE citation_key_norm IS NULL OR citation_key_norm = ''
            ORDER BY item_key
            """
        ).fetchall()
        return [str(row["item_key"]) for row in rows]

    @staticmethod
    def _norm_column_for_field(field: str) -> str:
        mapping = {
            "doi": "doi_norm",
            "citation_key": "citation_key_norm",
            "journal": "journal_norm",
        }
        column = mapping.get(field)
        if column is None:
            raise ValueError(f"Unsupported field for structured inspection: {field}")
        return column

    def list_item_keys_missing_field(self, field: str, *, limit: int = 5) -> list[str]:
        column = self._norm_column_for_field(field)
        rows = self._conn.execute(
            f"""
            SELECT item_key
            FROM documents
            WHERE {column} IS NULL OR {column} = ''
            ORDER BY item_key
            LIMIT ?
            """,
            (max(0, limit),),
        ).fetchall()
        return [str(row["item_key"]) for row in rows]

    def count_missing_field(self, field: str) -> int:
        column = self._norm_column_for_field(field)
        row = self._conn.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM documents
            WHERE {column} IS NULL OR {column} = ''
            """
        ).fetchone()
        return int(row["c"]) if row else 0

    def inspect_structured_fields(self, *, sample_limit: int = 5) -> dict[str, object]:
        doc_count = self.document_count()
        fields = ["doi", "citation_key", "journal"]
        details: dict[str, object] = {}
        for field in fields:
            missing = self.count_missing_field(field)
            present = max(0, doc_count - missing)
            details[field] = {
                "missing": missing,
                "present": present,
                "sample_missing_item_keys": self.list_item_keys_missing_field(field, limit=sample_limit),
            }
        return {
            "documents": doc_count,
            "fields": details,
        }

    def set_item_citation_key(self, item_key: str, citation_key: str) -> bool:
        clean = citation_key.strip()
        if not clean:
            return False

        row = self._conn.execute("SELECT item_json FROM documents WHERE item_key = ?", (item_key,)).fetchone()
        if row is None:
            return False

        item = Item.model_validate_json(str(row["item_json"]))
        item.citation_key = clean
        with self._conn:
            self._conn.execute(
                """
                UPDATE documents
                SET item_json = ?, citation_key_norm = ?
                WHERE item_key = ?
                """,
                (item.model_dump_json(), self._normalize_citation_key(clean), item_key),
            )
        return True

    def get_content_hash(self, item_key: str) -> str | None:
        row = self._conn.execute("SELECT content_hash FROM documents WHERE item_key = ?", (item_key,)).fetchone()
        if row is None:
            return None
        value = row["content_hash"]
        return str(value) if value else None

    def search_keyword(self, query: QuerySpec) -> list[SearchHit]:
        if not query.text:
            return self._search_by_filters_only(query, mode_name="keyword")

        filter_where, filter_params = self._structured_filter_sql(query, table_alias="documents")
        where_clauses = ["chunks_fts MATCH ?"]
        params: list[object] = [query.text]
        if filter_where:
            where_clauses.append(filter_where)
            params.extend(filter_params)
        where_sql = " AND ".join(where_clauses)

        # bm25() cannot be used safely inside grouped aggregate expressions on all SQLite builds,
        # so collect chunk-level results first and then collapse to unique item keys in Python.
        cursor = self._conn.execute(
            f"""
            SELECT chunks_fts.item_key, bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN documents ON documents.item_key = chunks_fts.item_key
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
            if item_key not in best_by_item:
                best_by_item[item_key] = score
            else:
                prev = best_by_item[item_key]
                # Smaller raw BM25 is better in SQLite FTS5.
                if prev is None or (score is not None and score < prev):
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
        filter_where, filter_params = self._structured_filter_sql(query)
        sql = "SELECT item_json, title, full_text FROM documents"
        if filter_where:
            sql += f" WHERE {filter_where}"
        sql += " ORDER BY item_key"
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
        prefix = f"{table_alias}." if table_alias else ""
        clauses: list[str] = []
        params: list[object] = []

        doi_norm = cls._normalize_doi(query.doi)
        if doi_norm:
            clauses.append(f"{prefix}doi_norm = ?")
            params.append(doi_norm)

        citation_key_norm = cls._normalize_citation_key(query.citation_key)
        if citation_key_norm:
            clauses.append(f"{prefix}citation_key_norm = ?")
            params.append(citation_key_norm)

        journal_norm = cls._normalize_journal(query.journal)
        if journal_norm:
            clauses.append(f"{prefix}journal_norm LIKE ?")
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
