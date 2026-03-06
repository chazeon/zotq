from __future__ import annotations

from pathlib import Path

from zotq.models import ChunkRecord, Item, QuerySpec, SearchMode
from zotq.storage import LexicalIndex


def _chunks(item_key: str, text: str) -> list[ChunkRecord]:
    return [ChunkRecord(chunk_id=f"{item_key}:0", item_key=item_key, ordinal=0, text=text)]


def _upsert(index: LexicalIndex, item: Item, text: str) -> None:
    index.upsert_item(item=item, chunks=_chunks(item.key, text), full_text=text)


def test_keyword_downranks_attachments_by_default(tmp_path: Path) -> None:
    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    try:
        query_text = "mantle hydration"
        article = Item(key="A-ARTICLE", item_type="journalArticle", title=query_text)
        attachment = Item(key="B-ATTACH", item_type="attachment", title=query_text)

        _upsert(index, article, query_text)
        _upsert(index, attachment, query_text)

        hits = index.search_keyword(
            QuerySpec(text=query_text, search_mode=SearchMode.KEYWORD, limit=5),
        )

        assert [hit.item.key for hit in hits[:2]] == ["A-ARTICLE", "B-ATTACH"]
        assert hits[0].score is not None
        assert hits[1].score is not None
        assert hits[0].score > hits[1].score
    finally:
        index.close()


def test_keyword_attachment_penalty_is_disabled_with_item_type_filter(tmp_path: Path) -> None:
    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    try:
        text = "igneous petrology"
        attachment = Item(key="ATTACH-ONLY", item_type="attachment", title=text)
        _upsert(index, attachment, text)

        without_filter = index.search_keyword(
            QuerySpec(text=text, search_mode=SearchMode.KEYWORD, limit=1),
        )[0]
        with_filter = index.search_keyword(
            QuerySpec(text=text, search_mode=SearchMode.KEYWORD, item_type="attachment", limit=1),
        )[0]

        assert without_filter.score is not None
        assert with_filter.score is not None
        assert with_filter.score > without_filter.score
    finally:
        index.close()


def test_keyword_scores_are_non_negative_and_descending(tmp_path: Path) -> None:
    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    try:
        query_text = "metamorphic facies"
        exact = Item(key="K-EXACT", item_type="journalArticle", title=query_text)
        weak = Item(key="K-WEAK", item_type="journalArticle", title="petrology overview")

        _upsert(index, exact, query_text)
        _upsert(index, weak, "regional petrology and mineral assemblages")

        hits = index.search_keyword(
            QuerySpec(text=query_text, search_mode=SearchMode.KEYWORD, limit=5),
        )
        scores = [hit.score for hit in hits]

        assert all(score is not None and score >= 0 for score in scores)
        assert scores == sorted(scores, reverse=True)
    finally:
        index.close()


def test_keyword_ties_are_deterministic_by_item_key(tmp_path: Path) -> None:
    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    try:
        text = "craton stability"
        item_b = Item(key="B-KEY", item_type="journalArticle", title=text)
        item_a = Item(key="A-KEY", item_type="journalArticle", title=text)

        _upsert(index, item_b, text)
        _upsert(index, item_a, text)

        hits = index.search_keyword(
            QuerySpec(text=text, search_mode=SearchMode.KEYWORD, limit=5),
        )

        assert [hit.item.key for hit in hits[:2]] == ["A-KEY", "B-KEY"]
    finally:
        index.close()


def test_fuzzy_ties_are_deterministic_by_item_key(tmp_path: Path) -> None:
    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    try:
        text = "tectonic inversion"
        item_b = Item(key="F-B", item_type="journalArticle", title=text)
        item_a = Item(key="F-A", item_type="journalArticle", title=text)

        _upsert(index, item_b, text)
        _upsert(index, item_a, text)

        hits = index.search_fuzzy(
            QuerySpec(text=text, search_mode=SearchMode.FUZZY, limit=5),
        )

        assert [hit.item.key for hit in hits[:2]] == ["F-A", "F-B"]
    finally:
        index.close()
