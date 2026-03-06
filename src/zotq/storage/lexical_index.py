"""SQLite-backed lexical index with FTS5."""

from __future__ import annotations

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
                content_hash TEXT
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
        if "content_hash" not in columns:
            with self._conn:
                self._conn.execute("ALTER TABLE documents ADD COLUMN content_hash TEXT")

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

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO documents(item_key, item_json, title, item_type, date, creators, tags, full_text, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_key) DO UPDATE SET
                    item_json=excluded.item_json,
                    title=excluded.title,
                    item_type=excluded.item_type,
                    date=excluded.date,
                    creators=excluded.creators,
                    tags=excluded.tags,
                    full_text=excluded.full_text,
                    content_hash=excluded.content_hash
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

    def get_content_hash(self, item_key: str) -> str | None:
        row = self._conn.execute("SELECT content_hash FROM documents WHERE item_key = ?", (item_key,)).fetchone()
        if row is None:
            return None
        value = row["content_hash"]
        return str(value) if value else None

    def search_keyword(self, query: QuerySpec) -> list[SearchHit]:
        if not query.text:
            return []

        # bm25() cannot be used safely inside grouped aggregate expressions on all SQLite builds,
        # so collect chunk-level results first and then collapse to unique item keys in Python.
        cursor = self._conn.execute(
            """
            SELECT item_key, bm25(chunks_fts) AS score
            FROM chunks_fts
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (query.text, max((query.limit + query.offset) * 20, 200)),
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
            return []

        target = query.text.lower()
        rows = self._conn.execute(
            "SELECT item_json, title, full_text FROM documents ORDER BY item_key"
        ).fetchall()

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

    def close(self) -> None:
        self._conn.close()
