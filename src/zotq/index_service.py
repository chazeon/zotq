"""Index lifecycle service with persistent lexical storage."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import hashlib
import json

from .embeddings import build_embedding_provider
from .errors import IndexNotReadyError, ModeNotSupportedError
from .models import BackendCapabilities, IndexConfig, IndexStatus, Item, QuerySpec, SearchHit, SearchMode, VectorRecord
from .pipeline import chunk_text, extract_item_text
from .storage import CheckpointStore, LexicalIndex, VectorIndex

ProgressCallback = Callable[[str, int, int | None], None]


class MockIndexService:
    """Persistent index service (name retained for compatibility)."""

    def __init__(self, config: IndexConfig) -> None:
        self._config = config
        self._index_dir = config.expanded_index_dir()
        self._index_dir.mkdir(parents=True, exist_ok=True)

        self._embedding = build_embedding_provider(config)
        self._lexical = LexicalIndex(self._index_dir / "lexical.sqlite3")
        self._vector = VectorIndex(self._index_dir / "vector.sqlite3")
        self._checkpoints = CheckpointStore(self._index_dir / "checkpoints.json")

    def _last_sync_at(self) -> datetime | None:
        payload = self._checkpoints.read()
        raw = payload.get("last_sync_at")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def status(self) -> IndexStatus:
        doc_count = self._lexical.document_count()
        chunk_count = self._lexical.chunk_count()
        return IndexStatus(
            ready=bool(self._config.enabled and doc_count > 0),
            enabled=self._config.enabled,
            provider=self._config.embedding_provider,
            model=self._config.embedding_model,
            document_count=doc_count,
            chunk_count=chunk_count,
            last_sync_at=self._last_sync_at(),
        )

    def capabilities(self) -> BackendCapabilities:
        lexical_ready = bool(self._config.enabled and self._lexical.document_count() > 0)
        vector_ready = bool(self._config.enabled and self._vector.chunk_count() > 0)
        return BackendCapabilities(
            keyword=lexical_ready,
            fuzzy=lexical_ready,
            semantic=lexical_ready and vector_ready,
            hybrid=lexical_ready and vector_ready,
            index_status=True,
            index_sync=True,
            index_rebuild=True,
        )

    @staticmethod
    def _item_content_hash(item: Item) -> str:
        payload = item.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha1(canonical.encode("utf-8")).hexdigest()

    def _ingest_items(
        self,
        items: list[Item],
        *,
        progress: ProgressCallback | None = None,
        skip_unchanged: bool = False,
    ) -> None:
        total = len(items)
        for index, item in enumerate(items, start=1):
            content_hash = self._item_content_hash(item)
            if skip_unchanged and self._lexical.get_content_hash(item.key) == content_hash:
                if progress is not None:
                    progress("index", index, total)
                continue

            full_text = extract_item_text(item)
            chunks = chunk_text(item.key, full_text)
            self._lexical.upsert_item(item=item, chunks=chunks, full_text=full_text, content_hash=content_hash)
            embeddings = self._embedding.embed_texts([chunk.text for chunk in chunks])
            vector_records: list[VectorRecord] = []
            for chunk, embedding in zip(chunks, embeddings):
                vector_records.append(
                    VectorRecord(
                        chunk_id=chunk.chunk_id,
                        item_key=item.key,
                        ordinal=chunk.ordinal,
                        embedding=embedding,
                    )
                )
            self._vector.upsert_item(item.key, vector_records)
            if progress is not None:
                progress("index", index, total)

    def sync(
        self,
        *,
        items: list[Item] | None = None,
        full: bool = False,
        progress: ProgressCallback | None = None,
    ) -> IndexStatus:
        if not self._config.enabled:
            raise IndexNotReadyError("Index operations are disabled by configuration.")

        if full:
            self._lexical.clear()
            self._vector.clear()

        if items:
            self._ingest_items(items, progress=progress, skip_unchanged=not full)

        self._checkpoints.write(last_sync_at=datetime.now().astimezone())
        return self.status()

    def rebuild(self, *, items: list[Item] | None = None, progress: ProgressCallback | None = None) -> IndexStatus:
        if not self._config.enabled:
            raise IndexNotReadyError("Index operations are disabled by configuration.")

        self._lexical.clear()
        self._vector.clear()
        if items:
            self._ingest_items(items, progress=progress)

        self._checkpoints.write(last_sync_at=datetime.now().astimezone())
        return self.status()

    def search(self, query: QuerySpec):
        status = self.status()
        if not status.enabled:
            raise IndexNotReadyError("Index is not ready.")
        if not status.ready:
            raise IndexNotReadyError("Index is not ready.")

        if query.search_mode == SearchMode.KEYWORD:
            return self._lexical.search_keyword(query)
        if query.search_mode == SearchMode.FUZZY:
            return self._lexical.search_fuzzy(query)
        if query.search_mode == SearchMode.SEMANTIC:
            return self._search_semantic(query)
        if query.search_mode == SearchMode.HYBRID:
            return self._search_hybrid(query)
        raise ModeNotSupportedError(f"Index mode not supported: {query.search_mode.value}")

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

    @classmethod
    def _matches_filters(cls, item: Item, query: QuerySpec) -> bool:
        if query.title and query.title.lower() not in (item.title or "").lower():
            return False
        if query.doi and cls._normalize_doi(query.doi) != cls._normalize_doi(item.doi):
            return False
        if query.journal and query.journal.lower() not in (item.journal or "").lower():
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

    def _search_semantic(self, query: QuerySpec) -> list[SearchHit]:
        if not query.text:
            return []
        if self._vector.chunk_count() == 0:
            raise IndexNotReadyError("Vector index is not ready.")

        query_vector = self._embedding.embed_text(query.text)
        vector_limit = max(query.vector_k or query.limit, query.limit + query.offset)
        ranked = self._vector.search(query_vector, limit=max(vector_limit, query.limit + query.offset), offset=0)

        scored: list[tuple[float, bool, str, SearchHit]] = []
        for item_key, score in ranked:
            item = self._lexical.get_item(item_key)
            if item is None:
                continue
            if not self._matches_filters(item, query):
                continue
            semantic_score = max(0.0, score) * self._attachment_penalty(item, query)
            hit = SearchHit(item=item, score=semantic_score, score_breakdown={"semantic": semantic_score})
            scored.append((semantic_score, self._is_attachment(item), item_key, hit))

        scored.sort(key=lambda row: (-row[0], row[1], row[2]))
        hits = [row[3] for row in scored]
        return hits[query.offset : query.offset + query.limit]

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
    def _normalize_signal_scores(scores: dict[str, float]) -> dict[str, float]:
        if not scores:
            return {}

        min_score = min(scores.values())
        max_score = max(scores.values())

        if max_score <= 0.0:
            return {key: 0.0 for key in scores}
        if abs(max_score - min_score) < 1e-12:
            return {key: 1.0 for key in scores}

        scale = max_score - min_score
        return {key: (value - min_score) / scale for key, value in scores.items()}

    def _search_hybrid(self, query: QuerySpec) -> list[SearchHit]:
        if not query.text:
            return []
        if self._vector.chunk_count() == 0:
            raise IndexNotReadyError("Vector index is not ready.")

        alpha = query.alpha if query.alpha is not None else 0.35
        lexical_limit = max(query.lexical_k or query.limit, query.limit + query.offset)
        vector_limit = max(query.vector_k or query.limit, query.limit + query.offset)

        lexical_query = query.model_copy(deep=True)
        lexical_query.search_mode = SearchMode.KEYWORD
        lexical_query.offset = 0
        lexical_query.limit = lexical_limit
        lexical_hits = self._lexical.search_keyword(lexical_query)
        lexical_scores_raw = {hit.item.key: max(0.0, hit.score or 0.0) for hit in lexical_hits}
        lexical_scores = self._normalize_signal_scores(lexical_scores_raw)

        query_vector = self._embedding.embed_text(query.text)
        vector_hits = self._vector.search(query_vector, limit=vector_limit, offset=0)
        vector_scores_raw = {item_key: max(0.0, score) for item_key, score in vector_hits}
        vector_scores = self._normalize_signal_scores(vector_scores_raw)

        candidate_keys = set(lexical_scores) | set(vector_scores)
        ranked: list[tuple[float, bool, str, SearchHit]] = []
        for item_key in candidate_keys:
            item = self._lexical.get_item(item_key)
            if item is None:
                continue
            if not self._matches_filters(item, query):
                continue
            lexical_score = lexical_scores.get(item_key, 0.0)
            vector_score = vector_scores.get(item_key, 0.0)
            hybrid_score = ((alpha * lexical_score) + ((1.0 - alpha) * vector_score)) * self._attachment_penalty(item, query)
            hit = SearchHit(
                item=item,
                score=hybrid_score,
                score_breakdown={
                    "hybrid": hybrid_score,
                    "lexical": lexical_score,
                    "vector": vector_score,
                    "lexical_raw": lexical_scores_raw.get(item_key, 0.0),
                    "vector_raw": vector_scores_raw.get(item_key, 0.0),
                },
            )
            ranked.append((hybrid_score, self._is_attachment(item), item_key, hit))

        ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
        hits = [row[3] for row in ranked]
        return hits[query.offset : query.offset + query.limit]

    def close(self) -> None:
        self._lexical.close()
        self._vector.close()
        self._embedding.close()
