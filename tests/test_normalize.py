from __future__ import annotations

from zotq.models import Item
from zotq.pipeline.normalize import item_to_text


def test_item_to_text_includes_doi_journal_and_citation_key() -> None:
    item = Item(
        key="XVMVWQZX",
        title="Thermodynamics with the Gruneisen parameter",
        abstract="Fundamentals and applications.",
        doi="10.1016/j.pepi.2018.10.006",
        journal="Physics of the Earth and Planetary Interiors",
        citation_key="staceyThermodynamicsGruneisenParameter2019",
    )

    text = item_to_text(item)
    assert "10.1016/j.pepi.2018.10.006" in text
    assert "Physics of the Earth and Planetary Interiors" in text
    assert "staceyThermodynamicsGruneisenParameter2019" in text
