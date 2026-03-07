from __future__ import annotations

from pathlib import Path
import sqlite3

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


def test_keyword_filter_only_path_supports_doi_journal_and_citation_key(tmp_path: Path) -> None:
    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    try:
        target = Item(
            key="TARGET",
            item_type="journalArticle",
            title="Thermodynamics with the Gruneisen parameter",
            doi="10.1016/j.pepi.2018.10.006",
            journal="Physics of the Earth and Planetary Interiors",
            citation_key="staceyThermodynamicsGruneisenParameter2019",
        )
        other = Item(
            key="OTHER",
            item_type="journalArticle",
            title="Mantle hydration",
            doi="10.1234/example",
            journal="Geophysical Journal",
            citation_key="nishi2015mantle",
        )
        _upsert(index, target, "thermodynamics gruneisen")
        _upsert(index, other, "mantle hydration")

        hits = index.search_keyword(
            QuerySpec(
                search_mode=SearchMode.KEYWORD,
                doi="doi:10.1016/j.pepi.2018.10.006",
                journal="planetary interiors",
                citation_key="staceythermodynamicsgruneisenparameter2019",
                limit=10,
            )
        )

        assert [hit.item.key for hit in hits] == ["TARGET"]
    finally:
        index.close()


def test_legacy_schema_migration_backfills_structured_norm_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "lexical.sqlite3"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE documents (
                item_key TEXT PRIMARY KEY,
                item_json TEXT NOT NULL,
                title TEXT,
                item_type TEXT,
                date TEXT,
                creators TEXT,
                tags TEXT,
                full_text TEXT
            );
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                item_key TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                text TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                chunk_id UNINDEXED,
                item_key UNINDEXED,
                text,
                tokenize='unicode61'
            );
            """
        )
        item = Item(
            key="LEGACY",
            item_type="journalArticle",
            title="Thermodynamics with the Gruneisen parameter",
            doi="10.1016/j.pepi.2018.10.006",
            journal="Physics of the Earth and Planetary Interiors",
            citation_key="staceyThermodynamicsGruneisenParameter2019",
        )
        conn.execute(
            """
            INSERT INTO documents(item_key, item_json, title, item_type, date, creators, tags, full_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.key,
                item.model_dump_json(),
                item.title,
                item.item_type,
                item.date,
                "",
                "",
                "thermodynamics gruneisen",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    index = LexicalIndex(db_path)
    try:
        rows = index._conn.execute(  # type: ignore[attr-defined]
            """
            SELECT field_name, value_norm
            FROM item_fields
            WHERE item_key = 'LEGACY'
            ORDER BY field_name
            """
        ).fetchall()
        field_names = {str(row["field_name"]) for row in rows}
        assert {"citation_key", "doi", "journal"}.issubset(field_names)

        identifiers = index._conn.execute(  # type: ignore[attr-defined]
            """
            SELECT id_type, id_norm
            FROM identifiers
            WHERE item_key = 'LEGACY'
            ORDER BY id_type
            """
        ).fetchall()
        assert [str(row["id_type"]) for row in identifiers] == ["citation_key", "doi"]

        hits = index.search_keyword(
            QuerySpec(
                search_mode=SearchMode.KEYWORD,
                doi="doi:10.1016/j.pepi.2018.10.006",
                citation_key="staceythermodynamicsgruneisenparameter2019",
                journal="planetary interiors",
                limit=5,
            )
        )
        assert [hit.item.key for hit in hits] == ["LEGACY"]
    finally:
        index.close()


def test_set_item_structured_fields_updates_v2_structured_rows(tmp_path: Path) -> None:
    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    try:
        item = Item(
            key="V2-UPDATE",
            item_type="journalArticle",
            title="Thermodynamics with the Gruneisen parameter",
        )
        _upsert(index, item, "thermodynamics gruneisen")

        assert index.set_item_structured_fields(
            "V2-UPDATE",
            doi="doi:10.1016/j.pepi.2018.10.006",
            citation_key="StaceyThermodynamicsGruneisenParameter2019",
            journal="Physics of the Earth and Planetary Interiors",
        )

        summary = index.inspect_structured_fields(sample_limit=5)
        assert summary["fields"]["doi"]["missing"] == 0
        assert summary["fields"]["citation_key"]["missing"] == 0
        assert summary["fields"]["journal"]["missing"] == 0

        hits = index.search_keyword(
            QuerySpec(
                search_mode=SearchMode.KEYWORD,
                doi="10.1016/j.pepi.2018.10.006",
                citation_key="staceythermodynamicsgruneisenparameter2019",
                journal="planetary interiors",
                limit=5,
            )
        )
        assert [hit.item.key for hit in hits] == ["V2-UPDATE"]

        identifier_rows = index._conn.execute(  # type: ignore[attr-defined]
            """
            SELECT id_type, id_norm
            FROM identifiers
            WHERE item_key = 'V2-UPDATE'
            ORDER BY id_type
            """
        ).fetchall()
        assert [str(row["id_type"]) for row in identifier_rows] == ["citation_key", "doi"]
    finally:
        index.close()


def test_structured_field_registry_populates_extended_fields(tmp_path: Path) -> None:
    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    try:
        item = Item(
            key="EXT-FIELDS",
            item_type="journalArticle",
            title="Extended fields",
            journal="Journal A",
            journal_abbreviation="J. A.",
            issn="1234-5678",
            volume="42",
            pages="100-120",
            language="en-US",
        )
        _upsert(index, item, "extended metadata")

        rows = index._conn.execute(  # type: ignore[attr-defined]
            """
            SELECT field_name, value_norm
            FROM item_fields
            WHERE item_key = 'EXT-FIELDS'
            ORDER BY field_name
            """
        ).fetchall()
        values = {str(row["field_name"]): str(row["value_norm"]) for row in rows}

        assert values["journal"] == "journal a"
        assert values["journal_abbreviation"] == "j. a."
        assert values["issn"] == "1234-5678"
        assert values["volume"] == "42"
        assert values["pages"] == "100-120"
        assert values["language"] == "en-us"
    finally:
        index.close()


def test_upsert_populates_creator_and_lexical_projection_tables(tmp_path: Path) -> None:
    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    try:
        item = Item(
            key="PROJ",
            item_type="journalArticle",
            title="Projection test",
            abstract="Projection abstract",
            journal="Projection Journal",
            tags=["mantle", "hydration"],
            creators=[
                {"first_name": "Ada", "last_name": "Lovelace", "creator_type": "author"},  # type: ignore[arg-type]
                {"first_name": "Grace", "last_name": "Hopper", "creator_type": "author"},  # type: ignore[arg-type]
            ],
        )
        _upsert(index, item, "projection body text")

        creator_rows = index._conn.execute(  # type: ignore[attr-defined]
            """
            SELECT ordinal, family, given, key_norm
            FROM item_creators
            WHERE item_key = 'PROJ'
            ORDER BY ordinal
            """
        ).fetchall()
        assert len(creator_rows) == 2
        assert str(creator_rows[0]["family"]) == "Lovelace"
        assert str(creator_rows[0]["given"]) == "Ada"
        assert str(creator_rows[0]["key_norm"]) == "lovelace ada"

        projection = index._conn.execute(  # type: ignore[attr-defined]
            """
            SELECT title, abstract, journal, creators, tags, body
            FROM lexical_docs
            WHERE item_key = 'PROJ'
            """
        ).fetchone()
        assert projection is not None
        assert str(projection["title"]) == "Projection test"
        assert str(projection["abstract"]) == "Projection abstract"
        assert str(projection["journal"]) == "Projection Journal"
        assert "Ada Lovelace" in str(projection["creators"])
        assert "mantle" in str(projection["tags"])
        assert "projection body text" in str(projection["body"])

        fts_rows = index._conn.execute(  # type: ignore[attr-defined]
            """
            SELECT COUNT(*) AS c
            FROM lexical_fts
            WHERE item_key = 'PROJ'
            """
        ).fetchone()
        assert fts_rows is not None
        assert int(fts_rows["c"]) == 1
    finally:
        index.close()


def test_missing_field_detection_supports_registry_fields(tmp_path: Path) -> None:
    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    try:
        with_issn = Item(
            key="HAS-ISSN",
            item_type="journalArticle",
            title="Has ISSN",
            issn="1111-2222",
        )
        without_issn = Item(
            key="MISS-ISSN",
            item_type="journalArticle",
            title="No ISSN",
        )
        _upsert(index, with_issn, "issn item")
        _upsert(index, without_issn, "missing issn item")

        assert index.count_missing_field("issn") == 1
        assert index.list_item_keys_missing_field("issn") == ["MISS-ISSN"]
    finally:
        index.close()


def test_inspect_structured_fields_reports_missing_counts_and_samples(tmp_path: Path) -> None:
    index = LexicalIndex(tmp_path / "lexical.sqlite3")
    try:
        has_fields = Item(
            key="HAS",
            item_type="journalArticle",
            title="Has fields",
            doi="10.1000/xyz",
            citation_key="hasKey",
            journal="Journal A",
        )
        missing_fields = Item(
            key="MISS",
            item_type="journalArticle",
            title="Missing fields",
        )
        _upsert(index, has_fields, "has fields text")
        _upsert(index, missing_fields, "missing fields text")

        summary = index.inspect_structured_fields(sample_limit=1)

        assert summary["documents"] == 2
        fields = summary["fields"]
        assert fields["doi"]["missing"] == 1
        assert fields["citation_key"]["missing"] == 1
        assert fields["journal"]["missing"] == 1
        assert len(fields["doi"]["sample_missing_item_keys"]) == 1
    finally:
        index.close()
