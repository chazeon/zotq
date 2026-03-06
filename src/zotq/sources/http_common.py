"""Shared parsing/filtering helpers for Zotero-style HTTP adapters."""

from __future__ import annotations

from collections.abc import Mapping

from ..models import Collection, Creator, Item, QuerySpec, SearchHit, Tag


JsonObject = Mapping[str, object]


def safe_lower(value: str | None) -> str:
    return (value or "").lower()


def extract_year(value: str | None) -> int | None:
    if not value:
        return None
    if len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None


def item_from_payload(payload: JsonObject) -> Item:
    data = payload.get("data")
    if isinstance(data, Mapping):
        record = data
    else:
        record = payload

    creators_in = record.get("creators", [])
    creators: list[Creator] = []
    if isinstance(creators_in, list):
        for creator in creators_in:
            if isinstance(creator, Mapping):
                creators.append(
                    Creator(
                        first_name=str(creator.get("firstName", "")) or None,
                        last_name=str(creator.get("lastName", "")) or None,
                    )
                )

    tags_in = record.get("tags", [])
    tags: list[str] = []
    if isinstance(tags_in, list):
        for tag in tags_in:
            if isinstance(tag, Mapping):
                value = tag.get("tag")
                if value:
                    tags.append(str(value))

    key = payload.get("key") or record.get("key")
    if not isinstance(key, str):
        key = ""

    item_type = record.get("itemType")
    title = record.get("title")
    date = record.get("date")
    abstract = record.get("abstractNote")

    return Item(
        key=key,
        item_type=str(item_type) if item_type is not None else None,
        title=str(title) if title is not None else None,
        date=str(date) if date is not None else None,
        creators=creators,
        tags=tags,
        abstract=str(abstract) if abstract is not None else None,
    )


def parse_item(payload: object) -> Item | None:
    if isinstance(payload, Mapping):
        return item_from_payload(payload)
    return None


def parse_items(payload: object) -> list[Item]:
    if not isinstance(payload, list):
        return []

    items: list[Item] = []
    for entry in payload:
        if isinstance(entry, Mapping):
            items.append(item_from_payload(entry))
    return items


def parse_collections(payload: object) -> list[Collection]:
    if not isinstance(payload, list):
        return []

    collections: list[Collection] = []
    for entry in payload:
        if not isinstance(entry, Mapping):
            continue

        data = entry.get("data")
        if not isinstance(data, Mapping):
            continue

        key = entry.get("key")
        name = data.get("name")
        parent = data.get("parentCollection")

        if isinstance(key, str) and isinstance(name, str):
            collections.append(
                Collection(
                    key=key,
                    name=name,
                    parent_collection=str(parent) if parent is not None else None,
                )
            )
    return collections


def parse_tags(payload: object) -> list[Tag]:
    if not isinstance(payload, list):
        return []

    tags: list[Tag] = []
    for entry in payload:
        if isinstance(entry, Mapping):
            tag = entry.get("tag")
            tag_type = entry.get("type")
            if isinstance(tag, str):
                tags.append(Tag(tag=tag, type=int(tag_type) if isinstance(tag_type, int) else None))
    return tags


def item_matches_filters(item: Item, query: QuerySpec) -> bool:
    if query.title and safe_lower(query.title) not in safe_lower(item.title):
        return False

    if query.item_type and item.item_type != query.item_type:
        return False

    if query.tags:
        item_tags = {t.lower() for t in item.tags}
        if not all(tag.lower() in item_tags for tag in query.tags):
            return False

    if query.creators:
        creator_blob = " ".join(
            f"{creator.first_name or ''} {creator.last_name or ''}".strip().lower() for creator in item.creators
        )
        if not all(c.lower() in creator_blob for c in query.creators):
            return False

    year = extract_year(item.date)
    if query.year_from is not None and year is not None and year < query.year_from:
        return False
    if query.year_to is not None and year is not None and year > query.year_to:
        return False

    return True


def filter_items(items: list[Item], query: QuerySpec) -> list[Item]:
    return [item for item in items if item_matches_filters(item, query)]


def score_item(item: Item, query: QuerySpec) -> float | None:
    if not query.text:
        return None
    return 1.0 if safe_lower(query.text) == safe_lower(item.title) else None


def to_hits(items: list[Item], query: QuerySpec) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for item in items:
        score = score_item(item, query)
        breakdown = {query.search_mode.value: score} if score is not None else {}
        hits.append(SearchHit(item=item, score=score, score_breakdown=breakdown))
    return hits
