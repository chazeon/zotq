"""Index lifecycle service with persistent lexical storage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from time import perf_counter

from .embeddings import build_embedding_provider
from .errors import IndexNotReadyError, ModeNotSupportedError
from .models import BackendCapabilities, IndexConfig, IndexStatus, Item, QuerySpec, SearchHit, SearchMode, VectorRecord
from .pipeline import chunk_text, extract_item_text
from .storage import CheckpointStore, LexicalIndex, VectorIndex

ProgressCallback = Callable[[str, int, int | None], None]


@dataclass
class StageTiming:
    started_at: float
    ended_at: float
    events: int
    current: int
    total: int | None


class RetrievalBenchmarkHarness:
    """Collects per-phase timing and progress counters for index lifecycle runs."""

    def __init__(self, *, now_fn: Callable[[], float] | None = None) -> None:
        self._now = now_fn or perf_counter
        self._started_at = self._now()
        self._stages: dict[str, StageTiming] = {}
        self._last_phase: str | None = None
        self._finished = False

    def observe(self, phase: str, current: int, total: int | None) -> None:
        now = self._now()
        phase_name = (phase or "").strip().lower()
        if not phase_name:
            return

        if self._last_phase and self._last_phase != phase_name:
            prev = self._stages.get(self._last_phase)
            if prev is not None and prev.ended_at < now:
                prev.ended_at = now

        stage = self._stages.get(phase_name)
        if stage is None:
            self._stages[phase_name] = StageTiming(
                started_at=now,
                ended_at=now,
                events=1,
                current=max(0, current),
                total=total,
            )
            self._last_phase = phase_name
            return

        stage.events += 1
        stage.current = max(0, current)
        stage.total = total
        stage.ended_at = now
        self._last_phase = phase_name

    @staticmethod
    def _elapsed_ms(started_at: float, ended_at: float) -> int:
        return max(0, int(round((ended_at - started_at) * 1000)))

    def finish(self) -> dict[str, object]:
        if self._finished:
            return self._build_payload(self._now())
        self._finished = True
        return self._build_payload(self._now())

    def _build_payload(self, finished_at: float) -> dict[str, object]:
        if self._last_phase:
            last_stage = self._stages.get(self._last_phase)
            if last_stage is not None and last_stage.ended_at < finished_at:
                last_stage.ended_at = finished_at

        stages_payload: dict[str, dict[str, int | None]] = {}
        stage_order: list[str] = []
        for phase, stage in self._stages.items():
            stage_order.append(phase)
            stages_payload[phase] = {
                "events": stage.events,
                "current": stage.current,
                "total": stage.total,
                "elapsed_ms": self._elapsed_ms(stage.started_at, stage.ended_at),
            }
        return {
            "total_ms": self._elapsed_ms(self._started_at, finished_at),
            "stage_order": stage_order,
            "stages": stages_payload,
        }


class MockIndexService:
    """Persistent index service (name retained for compatibility)."""

    def __init__(self, config: IndexConfig) -> None:
        self._config = config
        self._index_dir = config.expanded_index_dir()
        self._index_dir.mkdir(parents=True, exist_ok=True)

        self._embedding = build_embedding_provider(config)
        self._lexical = LexicalIndex(self._index_dir / "lexical.sqlite3")
        self._vector = VectorIndex(self._index_dir / "vector.sqlite3", backend=config.vector_backend)
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

    @staticmethod
    def _creator_blob(item: Item) -> str:
        return ", ".join(
            " ".join(part for part in [creator.first_name, creator.last_name] if part).strip()
            for creator in item.creators
        )

    @classmethod
    def _item_vector_text(cls, item: Item) -> str:
        tags = ", ".join(item.tags)
        parts = [
            item.title or "",
            item.abstract or "",
            cls._creator_blob(item),
            tags,
        ]
        return "\n".join(part for part in parts if part).strip()

    def _item_vector_hash(self, item: Item) -> str:
        payload = {
            "provider": self._config.embedding_provider,
            "model": self._config.embedding_model,
            "text": self._item_vector_text(item),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha1(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_item_sequence(items: list[Item]) -> list[Item]:
        ordered: list[Item] = []
        seen: set[str] = set()
        for item in items:
            key = (item.key or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(item)
        return ordered

    @staticmethod
    def _int_from_payload(value: object, *, default: int = 0) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return default
        return default

    @classmethod
    def _resume_plan(
        cls,
        *,
        items: list[Item],
        mode: str,
        ingest_state: dict[str, object] | None,
    ) -> tuple[list[Item], int, int, bool]:
        normalized_items = cls._normalize_item_sequence(items)
        if not normalized_items:
            return [], 0, 0, False

        if not ingest_state:
            return normalized_items, len(normalized_items), 0, False

        saved_mode = str(ingest_state.get("mode") or "").strip().lower()
        if saved_mode != mode:
            return normalized_items, len(normalized_items), 0, False

        remaining_raw = ingest_state.get("remaining_keys")
        if not isinstance(remaining_raw, list):
            return normalized_items, len(normalized_items), 0, False
        remaining_keys = [str(value).strip() for value in remaining_raw if str(value).strip()]
        if not remaining_keys:
            return normalized_items, len(normalized_items), 0, False

        total_saved = cls._int_from_payload(ingest_state.get("total"), default=len(normalized_items))
        done_saved = cls._int_from_payload(ingest_state.get("done"), default=max(0, total_saved - len(remaining_keys)))
        done_offset = max(0, min(done_saved, total_saved))

        by_key = {item.key: item for item in normalized_items}
        input_order_keys = [item.key for item in normalized_items]
        done_prefix_keys = set(input_order_keys[: max(0, min(done_offset, len(input_order_keys)))])
        planned: list[Item] = []
        planned_keys: set[str] = set()
        for key in remaining_keys:
            item = by_key.get(key)
            if item is None:
                continue
            planned.append(item)
            planned_keys.add(key)

        for item in normalized_items:
            if item.key in planned_keys:
                continue
            if item.key in done_prefix_keys:
                continue
            planned.append(item)
            planned_keys.add(item.key)

        total = max(total_saved, done_offset + len(planned))
        return planned, total, done_offset, True

    def _ingest_items(
        self,
        items: list[Item],
        *,
        progress: ProgressCallback | None = None,
        skip_unchanged: bool = False,
        checkpoint_mode: str | None = None,
        done_offset: int = 0,
        total_override: int | None = None,
    ) -> None:
        total = total_override if total_override is not None else len(items)
        remaining_keys = [item.key for item in items]
        for index, item in enumerate(items, start=1):
            current_done = done_offset + index
            content_hash = self._item_content_hash(item)
            lexical_hash = content_hash
            vector_hash = self._item_vector_hash(item)
            current_lexical_profile_version = self._config.lexical_profile_version
            current_vector_profile_version = self._config.vector_profile_version

            (
                existing_lexical_hash_raw,
                existing_vector_hash_raw,
                existing_content_hash,
                existing_lexical_profile_version_raw,
                existing_vector_profile_version_raw,
            ) = self._lexical.get_item_sync_state(item.key)
            existing_lexical_hash = existing_lexical_hash_raw
            existing_vector_hash = existing_vector_hash_raw
            existing_lexical_profile_version = (
                current_lexical_profile_version
                if existing_lexical_profile_version_raw is None
                else existing_lexical_profile_version_raw
            )
            existing_vector_profile_version = (
                current_vector_profile_version
                if existing_vector_profile_version_raw is None
                else existing_vector_profile_version_raw
            )
            if existing_lexical_hash is None and existing_content_hash:
                existing_lexical_hash = existing_content_hash
            if existing_vector_hash is None:
                existing_item = self._lexical.get_item(item.key)
                if existing_item is not None and self._vector.has_item(item.key):
                    existing_vector_hash = self._item_vector_hash(existing_item)

            lexical_changed = (
                existing_lexical_hash != lexical_hash
                or existing_lexical_profile_version != current_lexical_profile_version
            )
            vector_changed = (
                existing_vector_hash != vector_hash
                or existing_vector_profile_version != current_vector_profile_version
            )

            if skip_unchanged and not lexical_changed and not vector_changed:
                # Persist migrated hash columns lazily so future syncs avoid fallback checks.
                if (
                    existing_content_hash != content_hash
                    or existing_lexical_hash_raw != lexical_hash
                    or existing_vector_hash_raw != vector_hash
                    or existing_lexical_profile_version_raw != current_lexical_profile_version
                    or existing_vector_profile_version_raw != current_vector_profile_version
                ):
                    self._lexical.set_item_hashes(
                        item.key,
                        lexical_hash=lexical_hash,
                        vector_hash=vector_hash,
                        content_hash=content_hash,
                        lexical_profile_version=current_lexical_profile_version,
                        vector_profile_version=current_vector_profile_version,
                    )
                if checkpoint_mode:
                    next_remaining = remaining_keys[index:]
                    self._checkpoints.write_ingest(
                        mode=checkpoint_mode,
                        total=total,
                        done=current_done,
                        remaining_keys=next_remaining,
                    )
                if progress is not None:
                    progress("index", current_done, total)
                continue

            if lexical_changed:
                stored_vector_hash = vector_hash if not vector_changed else existing_vector_hash_raw
                full_text = extract_item_text(item)
                chunks = chunk_text(item.key, full_text)
                self._lexical.upsert_item(
                    item=item,
                    chunks=chunks,
                    full_text=full_text,
                    content_hash=content_hash,
                    lexical_hash=lexical_hash,
                    vector_hash=stored_vector_hash,
                    lexical_profile_version=current_lexical_profile_version,
                    vector_profile_version=(
                        current_vector_profile_version if not vector_changed else existing_vector_profile_version_raw
                    ),
                )
            else:
                self._lexical.set_item_hashes(
                    item.key,
                    lexical_hash=lexical_hash,
                    content_hash=content_hash,
                    vector_hash=vector_hash if not vector_changed else None,
                    lexical_profile_version=current_lexical_profile_version,
                    vector_profile_version=current_vector_profile_version if not vector_changed else None,
                )

            if vector_changed:
                vector_text = self._item_vector_text(item)
                vector_chunks = chunk_text(item.key, vector_text)
                embeddings = self._embedding.embed_texts([chunk.text for chunk in vector_chunks]) if vector_chunks else []
                vector_records: list[VectorRecord] = []
                for chunk, embedding in zip(vector_chunks, embeddings):
                    vector_records.append(
                        VectorRecord(
                            chunk_id=chunk.chunk_id,
                            item_key=item.key,
                            ordinal=chunk.ordinal,
                            embedding=embedding,
                        )
                    )
                self._vector.upsert_item(item.key, vector_records)
                self._lexical.set_item_hashes(
                    item.key,
                    vector_hash=vector_hash,
                    vector_profile_version=current_vector_profile_version,
                )

            if checkpoint_mode:
                next_remaining = remaining_keys[index:]
                self._checkpoints.write_ingest(
                    mode=checkpoint_mode,
                    total=total,
                    done=current_done,
                    remaining_keys=next_remaining,
                )
            if progress is not None:
                progress("index", current_done, total)

    def sync(
        self,
        *,
        items: list[Item] | None = None,
        full: bool = False,
        progress: ProgressCallback | None = None,
    ) -> IndexStatus:
        if not self._config.enabled:
            raise IndexNotReadyError("Index operations are disabled by configuration.")

        normalized_items = self._normalize_item_sequence(items or [])
        mode = "full" if full else "incremental"
        ingest_state = self._checkpoints.ingest_state()
        planned_items, total_items, done_offset, resume = self._resume_plan(
            items=normalized_items,
            mode=mode,
            ingest_state=ingest_state,
        )

        if full and not resume:
            self._lexical.clear()
            self._vector.clear()

        if planned_items:
            self._checkpoints.write_ingest(
                mode=mode,
                total=total_items,
                done=done_offset,
                remaining_keys=[item.key for item in planned_items],
            )
            self._ingest_items(
                planned_items,
                progress=progress,
                skip_unchanged=not full,
                checkpoint_mode=mode,
                done_offset=done_offset,
                total_override=total_items,
            )
        else:
            self._checkpoints.clear_ingest()

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

    def list_items_missing_citation_key(self) -> list[str]:
        return self._lexical.list_item_keys_missing_citation_key()

    def get_collect_checkpoint(self) -> dict[str, object] | None:
        return self._checkpoints.collect_state()

    def write_collect_checkpoint(
        self,
        *,
        scope: str,
        full: bool,
        expected_total: int | None,
        paging_mode: str = "offset",
        next_offset: int | None = None,
        next_cursor: str | None = None,
        collected_keys: list[str],
    ) -> None:
        self._checkpoints.write_collect(
            scope=scope,
            full=full,
            expected_total=expected_total,
            paging_mode=paging_mode,
            next_offset=next_offset,
            next_cursor=next_cursor,
            collected_keys=collected_keys,
        )

    def clear_collect_checkpoint(self) -> None:
        self._checkpoints.clear_collect()

    def list_items_missing_field(self, field: str) -> list[str]:
        return self._lexical.list_item_keys_missing_field(field)

    def list_profile_mismatch_item_keys(self) -> list[str]:
        lexical = self._lexical.list_item_keys_with_profile_mismatch(
            "lexical_profile_version",
            self._config.lexical_profile_version,
        )
        vector = self._lexical.list_item_keys_with_profile_mismatch(
            "vector_profile_version",
            self._config.vector_profile_version,
        )
        return sorted(set(lexical) | set(vector))

    def set_item_citation_key(self, item_key: str, citation_key: str) -> bool:
        return self._lexical.set_item_citation_key(item_key, citation_key)

    def set_item_structured_fields(
        self,
        item_key: str,
        *,
        doi: str | None = None,
        citation_key: str | None = None,
        journal: str | None = None,
    ) -> bool:
        return self._lexical.set_item_structured_fields(
            item_key,
            doi=doi,
            citation_key=citation_key,
            journal=journal,
        )

    def inspect_index(self, *, sample_limit: int = 5) -> dict[str, object]:
        lexical = self._lexical.inspect_structured_fields(
            sample_limit=sample_limit,
            lexical_profile_version=self._config.lexical_profile_version,
            vector_profile_version=self._config.vector_profile_version,
        )
        payload: dict[str, object] = {
            "documents": lexical.get("documents", 0),
            "chunks": self._lexical.chunk_count(),
            "vectors": self._vector.chunk_count(),
            "fields": lexical.get("fields", {}),
        }
        profiles = lexical.get("profiles")
        if isinstance(profiles, dict):
            payload["profiles"] = profiles
        return payload

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
        if not query.include_attachments and not query.item_type and cls._is_attachment(item):
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

        allowed_item_keys = self._lexical.item_keys_for_structured_filters(query)
        if allowed_item_keys is not None and not allowed_item_keys:
            return []

        query_vector = self._embedding.embed_text(query.text)
        vector_limit = max(query.vector_k or query.limit, query.limit + query.offset)
        ranked = self._vector.search(
            query_vector,
            limit=max(vector_limit, query.limit + query.offset),
            offset=0,
            allowed_item_keys=allowed_item_keys,
        )

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

        allowed_item_keys = self._lexical.item_keys_for_structured_filters(query)
        if allowed_item_keys is not None and not allowed_item_keys:
            return []

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
        vector_hits = self._vector.search(query_vector, limit=vector_limit, offset=0, allowed_item_keys=allowed_item_keys)
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
