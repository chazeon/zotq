"""Attachment extraction entrypoints.

v1 skeleton: metadata/abstract text indexing only.
Future work: PDF/HTML/TXT attachment extraction.
"""

from __future__ import annotations

from ..models import Item
from .normalize import item_to_text


def extract_item_text(item: Item) -> str:
    """Return indexable text for an item.

    This currently uses item metadata/abstract only.
    """

    return item_to_text(item)
