"""Parser-backed BibTeX helpers for citation-key extraction and deterministic output."""

from __future__ import annotations

from collections.abc import Iterable

import bibtexparser
from bibtexparser.bibdatabase import BibDatabase
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter


_NON_ENTRY_TYPES = {"comment", "preamble", "string"}


def _fallback_entry_ids(text: str | None) -> list[str]:
    raw = text or ""
    out: list[str] = []
    length = len(raw)
    index = 0

    while index < length:
        at = raw.find("@", index)
        if at < 0:
            break
        cursor = at + 1
        while cursor < length and raw[cursor].isspace():
            cursor += 1
        type_start = cursor
        while cursor < length and raw[cursor].isalpha():
            cursor += 1
        entry_type = raw[type_start:cursor].strip().lower()
        while cursor < length and raw[cursor].isspace():
            cursor += 1
        if cursor >= length or raw[cursor] not in "{(":
            index = at + 1
            continue

        opener = raw[cursor]
        closer = "}" if opener == "{" else ")"
        cursor += 1
        body_start = cursor
        depth = 1
        while cursor < length and depth > 0:
            char = raw[cursor]
            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
            cursor += 1
        body = raw[body_start : cursor - 1] if depth == 0 else raw[body_start:]
        index = cursor

        if entry_type in _NON_ENTRY_TYPES:
            continue
        comma_at = body.find(",")
        if comma_at < 0:
            continue
        key = body[:comma_at].strip()
        if key:
            out.append(key)

    return out


def _parse_bibtex(text: str | None) -> BibDatabase | None:
    raw = (text or "").strip()
    if not raw:
        return None
    parser = BibTexParser(common_strings=True)
    try:
        return bibtexparser.loads(raw, parser=parser)
    except Exception:
        return None


def _entry_ids(db: BibDatabase | None) -> list[str]:
    if db is None:
        return []
    keys: list[str] = []
    for entry in db.entries:
        key = str(entry.get("ID", "")).strip()
        if key:
            keys.append(key)
    return keys


def bibtex_citation_key(text: str | None) -> str | None:
    keys = _entry_ids(_parse_bibtex(text))
    if not keys:
        keys = _fallback_entry_ids(text)
    return keys[0] if keys else None


def bibtex_citation_keys(text: str | None) -> list[str]:
    keys = _entry_ids(_parse_bibtex(text))
    if keys:
        return keys
    return _fallback_entry_ids(text)


def _deterministic_writer() -> BibTexWriter:
    writer = BibTexWriter()
    writer.indent = "  "
    writer.order_entries_by = ("ID",)
    writer.entry_separator = "\n\n"
    writer.add_trailing_comma = False
    return writer


def canonicalize_bibtex_text(text: str | None) -> str | None:
    db = _parse_bibtex(text)
    if db is None or not db.entries:
        raw = (text or "").strip()
        return raw or None
    return _deterministic_writer().write(db).strip()


def canonicalize_bibtex_texts(chunks: Iterable[str]) -> str:
    entries: list[dict[str, str]] = []
    fallback_chunks: list[str] = []
    for chunk in chunks:
        db = _parse_bibtex(chunk)
        if db is None or not db.entries:
            raw = (chunk or "").strip()
            if raw:
                fallback_chunks.append(raw)
            continue
        entries.extend(db.entries)

    if not entries:
        return "\n\n".join(fallback_chunks)

    merged = BibDatabase()
    merged.entries = entries
    return _deterministic_writer().write(merged).strip()
