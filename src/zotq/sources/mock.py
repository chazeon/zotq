"""Deterministic mock source adapter for local development and tests."""

from __future__ import annotations

from difflib import SequenceMatcher

from ..models import BackendCapabilities, Collection, Creator, Item, QuerySpec, SearchHit, SearchMode, Tag

MOCK_ITEMS: list[Item] = [
    Item(
        key="D6GJQP57",
        item_type="journalArticle",
        title="Water in the Mantle",
        date="2005",
        creators=[Creator(first_name="E.", last_name="Ohtani")],
        tags=["mantle", "water"],
        abstract="Review of water storage and transport in the deep mantle.",
    ),
    Item(
        key="MI26RYRR",
        item_type="journalArticle",
        title="Mantle hydration",
        date="2015",
        creators=[Creator(first_name="Masayuki", last_name="Nishi")],
        tags=["mantle", "hydration"],
        abstract="The fate of water in subducting slabs and lower mantle reservoirs.",
        citation_key="nishiMantleHydration2015",
    ),
    Item(
        key="XJP5WU22",
        item_type="journalArticle",
        title="Water in Earth's Mantle: The Role of Nominally Anhydrous Minerals",
        date="1992",
        creators=[Creator(first_name="David", last_name="Bell")],
        tags=["mantle", "minerals"],
        abstract="Nominally anhydrous minerals can store significant water.",
    ),
    Item(
        key="HHAIYC9Q",
        item_type="journalArticle",
        title="Retention of water in subducted slabs under core-mantle boundary conditions",
        date="2024",
        creators=[Creator(first_name="Yutaro", last_name="Tsutsumi")],
        tags=["subduction", "mantle", "water"],
        abstract="Experiments on water retention at deep mantle boundary conditions.",
    ),
]

MOCK_COLLECTIONS: list[Collection] = [
    Collection(key="3X8QMPSN", name="Geophysics"),
    Collection(key="8C46NG5G", name="AI"),
]

MOCK_TAGS: list[Tag] = [
    Tag(tag="mantle", type=0),
    Tag(tag="water", type=0),
    Tag(tag="subduction", type=0),
]


def _blob(item: Item) -> str:
    creators = " ".join(filter(None, [c.first_name or "" for c in item.creators] + [c.last_name or "" for c in item.creators]))
    parts = [
        item.title or "",
        item.abstract or "",
        item.doi or "",
        item.journal or "",
        item.citation_key or "",
        " ".join(item.tags),
        creators,
        item.date or "",
    ]
    return " ".join(parts).lower()


class MockSourceAdapter:
    """In-memory adapter implementing all v1 read/query methods."""

    def __init__(self, *, semantic_enabled: bool = True, fuzzy_enabled: bool = True) -> None:
        self._capabilities = BackendCapabilities(
            keyword=True,
            fuzzy=fuzzy_enabled,
            semantic=semantic_enabled,
            hybrid=semantic_enabled,
            index_status=True,
            index_sync=True,
            index_rebuild=True,
        )

    def health(self) -> dict[str, str]:
        return {"status": "ok", "adapter": "mock"}

    def capabilities(self) -> BackendCapabilities:
        return self._capabilities

    def get_item(self, key: str) -> Item | None:
        for item in MOCK_ITEMS:
            if item.key == key:
                return item
        return None

    def get_item_bibtex(self, key: str) -> str | None:
        item = self.get_item(key)
        if item is None:
            return None
        citekey = item.citation_key or f"{item.key.lower()}Key"
        title = item.title or item.key
        return f"@article{{{citekey},\n  title = {{{title}}},\n}}\n"

    def get_item_citation_key_rpc(self, key: str) -> str | None:
        item = self.get_item(key)
        if item is None:
            return None
        return item.citation_key

    def get_items_citation_keys_rpc(self, keys: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for key in keys:
            value = self.get_item_citation_key_rpc(key)
            if value:
                out[key] = value
        return out

    def get_items_bibtex(self, keys: list[str]) -> str | None:
        entries: list[str] = []
        for key in keys:
            entry = self.get_item_bibtex(key)
            if entry:
                entries.append(entry.strip())
        if not entries:
            return None
        return "\n\n".join(entries)

    def get_item_bibliography(
        self,
        key: str,
        *,
        style: str | None = None,
        locale: str | None = None,
        linkwrap: bool | None = None,
    ) -> str | None:
        item = self.get_item(key)
        if item is None:
            return None
        style_prefix = f"[{style}] " if style else ""
        locale_suffix = f" ({locale})" if locale else ""
        return f"{style_prefix}{item.title or item.key}{locale_suffix}"

    def get_items_bibliography(
        self,
        keys: list[str],
        *,
        style: str | None = None,
        locale: str | None = None,
        linkwrap: bool | None = None,
    ) -> str | None:
        entries: list[str] = []
        for key in keys:
            entry = self.get_item_bibliography(key, style=style, locale=locale, linkwrap=linkwrap)
            if entry:
                entries.append(entry)
        if not entries:
            return None
        return "\n\n".join(entries)

    def list_collections(self) -> list[Collection]:
        return list(MOCK_COLLECTIONS)

    def list_tags(self) -> list[Tag]:
        return list(MOCK_TAGS)

    def list_items(self, *, limit: int = 100, offset: int = 0) -> list[Item]:
        return list(MOCK_ITEMS[offset : offset + limit])

    def count_items(self) -> int | None:
        return len(MOCK_ITEMS)

    def search_items(self, query: QuerySpec) -> list[SearchHit]:
        if not query.text:
            candidates = list(MOCK_ITEMS)
        else:
            mode = query.search_mode
            text = query.text.lower()

            if mode == SearchMode.FUZZY:
                candidates = self._fuzzy_candidates(text)
            elif mode in {SearchMode.SEMANTIC, SearchMode.HYBRID}:
                candidates = self._semantic_candidates(text)
            else:
                candidates = self._keyword_candidates(text)

        filtered = [item for item in candidates if self._matches_filters(item, query)]
        sliced = filtered[query.offset : query.offset + query.limit]

        hits: list[SearchHit] = []
        for item in sliced:
            score = self._score_item(item, query)
            hits.append(SearchHit(item=item, score=score, score_breakdown={query.search_mode.value: score}))

        return hits

    def _keyword_candidates(self, text: str) -> list[Item]:
        return [item for item in MOCK_ITEMS if text in _blob(item)]

    def _fuzzy_candidates(self, text: str) -> list[Item]:
        if not text:
            return list(MOCK_ITEMS)

        out: list[Item] = []
        for item in MOCK_ITEMS:
            title = (item.title or "").lower()
            blob = _blob(item)
            ratio = max(SequenceMatcher(None, text, title).ratio(), SequenceMatcher(None, text, blob).ratio())
            if ratio >= 0.45 or text in blob:
                out.append(item)
        return out

    def _semantic_candidates(self, text: str) -> list[Item]:
        # Mock semantic signal: keyword matching on abstract + tags.
        return [item for item in MOCK_ITEMS if text in _blob(item) or any(tok in _blob(item) for tok in text.split())]

    def _matches_filters(self, item: Item, query: QuerySpec) -> bool:
        if query.title and query.title.lower() not in (item.title or "").lower():
            return False

        if query.doi and (self._normalize_doi(query.doi) != self._normalize_doi(item.doi)):
            return False

        if query.journal and query.journal.lower() not in (item.journal or "").lower():
            return False

        if query.citation_key and query.citation_key.strip().lower() != (item.citation_key or "").strip().lower():
            return False

        if query.item_type and query.item_type != item.item_type:
            return False

        if query.tags:
            item_tags = {t.lower() for t in item.tags}
            if not all(t.lower() in item_tags for t in query.tags):
                return False

        if query.creators:
            creator_blob = " ".join(
                f"{creator.first_name or ''} {creator.last_name or ''}".strip().lower() for creator in item.creators
            )
            for creator_query in query.creators:
                if creator_query.lower() not in creator_blob:
                    return False

        item_year: int | None = None
        if item.date and item.date[:4].isdigit():
            item_year = int(item.date[:4])

        if query.year_from is not None and item_year is not None and item_year < query.year_from:
            return False

        if query.year_to is not None and item_year is not None and item_year > query.year_to:
            return False

        return True

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

    def _score_item(self, item: Item, query: QuerySpec) -> float:
        if not query.text:
            return 0.5

        text = query.text.lower()
        title = (item.title or "").lower()

        if text == title:
            return 1.0
        if text in title:
            return 0.9
        if text in _blob(item):
            return 0.8

        return max(0.1, SequenceMatcher(None, text, title).ratio())
