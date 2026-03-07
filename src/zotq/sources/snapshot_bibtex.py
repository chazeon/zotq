"""BibTeX snapshot source adapter."""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
import re

import bibtexparser
from bibtexparser.bibdatabase import BibDatabase
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter

from ..errors import ConfigError
from ..models import BackendCapabilities, Collection, Creator, Item, ProfileConfig, QuerySpec, SearchHit, SearchMode, Tag
from .http_common import filter_items, to_hits


def _deterministic_writer() -> BibTexWriter:
    writer = BibTexWriter()
    writer.indent = "  "
    writer.order_entries_by = ("ID",)
    writer.entry_separator = "\n\n"
    writer.add_trailing_comma = False
    return writer


class BibtexSnapshotSourceAdapter:
    """Offline source adapter backed by a local BibTeX snapshot file."""

    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile
        bib_path_raw = profile.snapshot.bib_path.strip()
        if not bib_path_raw:
            raise ConfigError("snapshot mode requires profiles.<name>.snapshot.bib_path")

        bib_path = Path(bib_path_raw).expanduser()
        if not bib_path.exists():
            raise ConfigError(f"snapshot BibTeX file not found: {bib_path}")
        if not bib_path.is_file():
            raise ConfigError(f"snapshot BibTeX path is not a file: {bib_path}")

        try:
            raw = bib_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Failed to read snapshot BibTeX file: {bib_path}: {exc}") from exc

        parser = BibTexParser(common_strings=True)
        try:
            database = bibtexparser.loads(raw, parser=parser)
        except Exception as exc:
            raise ConfigError(f"Failed to parse snapshot BibTeX file: {bib_path}: {exc}") from exc

        self._bib_path = bib_path
        self._entries_by_key: dict[str, dict[str, str]] = {}
        self._items: list[Item] = []

        for raw_entry in database.entries:
            key = str(raw_entry.get("ID", "")).strip()
            if not key or key in self._entries_by_key:
                continue
            entry = {str(k): str(v) for k, v in raw_entry.items() if v is not None}
            self._entries_by_key[key] = entry
            self._items.append(self._item_from_entry(key, entry))

    def health(self) -> dict[str, str]:
        return {"status": "ok", "adapter": "snapshot-bibtex", "path": str(self._bib_path)}

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            keyword=True,
            fuzzy=True,
            semantic=False,
            hybrid=False,
            index_status=True,
            index_sync=True,
            index_rebuild=True,
        )

    def search_items(self, query: QuerySpec) -> list[SearchHit]:
        text = (query.text or "").strip().lower()

        if query.search_mode == SearchMode.FUZZY:
            candidates = self._fuzzy_candidates(text)
        else:
            candidates = self._keyword_candidates(text)

        if query.collection:
            candidates = [item for item in candidates if query.collection in item.collections]

        filtered = filter_items(candidates, query)
        sliced = filtered[query.offset : query.offset + query.limit]
        return to_hits(sliced, query)

    def list_items(self, *, limit: int = 100, offset: int = 0) -> list[Item]:
        if limit <= 0:
            return []
        return list(self._items[offset : offset + limit])

    def count_items(self) -> int | None:
        return len(self._items)

    def get_item(self, key: str) -> Item | None:
        for item in self._items:
            if item.key == key:
                return item
        return None

    def get_items(self, keys: list[str]) -> list[Item]:
        out: list[Item] = []
        for key in keys:
            item = self.get_item(key)
            if item is not None:
                out.append(item)
        return out

    def get_item_bibtex(self, key: str) -> str | None:
        entry = self._entries_by_key.get(key)
        if entry is None:
            return None
        return self._serialize_entries([entry])

    def get_item_citation_key_rpc(self, key: str) -> str | None:
        return key if key in self._entries_by_key else None

    def get_items_citation_keys_rpc(self, keys: list[str]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for key in keys:
            value = self.get_item_citation_key_rpc(key)
            if value:
                resolved[key] = value
        return resolved

    def get_items_bibtex(self, keys: list[str]) -> str | None:
        entries: list[dict[str, str]] = []
        for key in keys:
            entry = self._entries_by_key.get(key)
            if entry is not None:
                entries.append(entry)
        if not entries:
            return None
        return self._serialize_entries(entries)

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
            value = self.get_item_bibliography(key, style=style, locale=locale, linkwrap=linkwrap)
            if value:
                entries.append(value)
        if not entries:
            return None
        return "\n\n".join(entries)

    def list_collections(self) -> list[Collection]:
        return []

    def list_tags(self) -> list[Tag]:
        tags: set[str] = set()
        for item in self._items:
            for tag in item.tags:
                value = tag.strip()
                if value:
                    tags.add(value)
        return [Tag(tag=tag, type=0) for tag in sorted(tags, key=str.lower)]

    @staticmethod
    def _entry_type_to_item_type(value: str | None) -> str:
        normalized = (value or "").strip().lower()
        if normalized == "article":
            return "journalArticle"
        if normalized == "book":
            return "book"
        if normalized in {"inproceedings", "conference", "proceedings"}:
            return "conferencePaper"
        if normalized == "phdthesis":
            return "thesis"
        if normalized == "mastersthesis":
            return "thesis"
        return normalized or "document"

    @staticmethod
    def _parse_authors(value: str | None) -> list[Creator]:
        raw = (value or "").strip()
        if not raw:
            return []

        tokens = [token.strip() for token in re.split(r"(?i)\s+and\s+", raw) if token.strip()]
        creators: list[Creator] = []
        for token in tokens:
            normalized = token.strip().strip("{}")
            if "," in normalized:
                last_name, first_name = normalized.split(",", 1)
                creators.append(Creator(first_name=first_name.strip() or None, last_name=last_name.strip() or None))
                continue
            parts = normalized.split()
            if not parts:
                continue
            if len(parts) == 1:
                creators.append(Creator(first_name=None, last_name=parts[0]))
                continue
            creators.append(Creator(first_name=" ".join(parts[:-1]) or None, last_name=parts[-1]))
        return creators

    @staticmethod
    def _parse_keywords(value: str | None) -> list[str]:
        raw = (value or "").strip()
        if not raw:
            return []
        out: list[str] = []
        for part in re.split(r"[;,]", raw):
            token = part.strip()
            if token:
                out.append(token)
        return out

    @classmethod
    def _item_from_entry(cls, key: str, entry: dict[str, str]) -> Item:
        journal = entry.get("journal") or entry.get("journaltitle") or entry.get("booktitle")
        year = entry.get("year")
        return Item(
            key=key,
            item_type=cls._entry_type_to_item_type(entry.get("ENTRYTYPE")),
            title=entry.get("title"),
            date=year,
            creators=cls._parse_authors(entry.get("author")),
            tags=cls._parse_keywords(entry.get("keywords")),
            abstract=entry.get("abstract"),
            doi=entry.get("doi"),
            journal=journal,
            citation_key=key,
            source_payload=dict(entry),
        )

    @staticmethod
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

    def _keyword_candidates(self, text: str) -> list[Item]:
        if not text:
            return list(self._items)
        return [item for item in self._items if text in self._blob(item)]

    def _fuzzy_candidates(self, text: str) -> list[Item]:
        if not text:
            return list(self._items)

        out: list[Item] = []
        for item in self._items:
            title = (item.title or "").lower()
            blob = self._blob(item)
            ratio = max(SequenceMatcher(None, text, title).ratio(), SequenceMatcher(None, text, blob).ratio())
            if ratio >= 0.45 or text in blob:
                out.append(item)
        return out

    @staticmethod
    def _serialize_entries(entries: list[dict[str, str]]) -> str:
        database = BibDatabase()
        database.entries = [dict(entry) for entry in entries]
        return _deterministic_writer().write(database).strip()
