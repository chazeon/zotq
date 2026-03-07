"""Normalization helpers for converting items into indexable text."""

from __future__ import annotations

from ..models import Item


def item_to_text(item: Item) -> str:
    creators = ", ".join(
        " ".join(part for part in [creator.first_name, creator.last_name] if part).strip()
        for creator in item.creators
    )
    tags = ", ".join(item.tags)

    parts = [
        item.title or "",
        item.abstract or "",
        item.doi or "",
        item.journal or "",
        item.citation_key or "",
        creators,
        tags,
        item.date or "",
        item.item_type or "",
    ]

    return "\n".join(part for part in parts if part).strip()
