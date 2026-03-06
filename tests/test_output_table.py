from __future__ import annotations

from zotq.models import OutputFormat
from zotq.output import render_payload


def test_table_render_search_payload() -> None:
    payload = {
        "requested_mode": "hybrid",
        "executed_mode": "hybrid",
        "limit": 2,
        "offset": 0,
        "total": 2,
        "hits": [
            {
                "item": {
                    "key": "MI26RYRR",
                    "item_type": "journalArticle",
                    "title": "Mantle hydration",
                    "date": "2015",
                },
                "score": 0.99,
                "score_breakdown": {"hybrid": 0.99},
            },
            {
                "item": {
                    "key": "MKCL8ZBE",
                    "item_type": "journalArticle",
                    "title": "Limited Mantle Hydration by Bending Faults",
                    "date": "2021",
                },
                "score": 0.85,
                "score_breakdown": {"hybrid": 0.85},
            },
        ],
    }

    rendered = render_payload(payload, OutputFormat.TABLE)
    assert "Executed Mode" in rendered
    assert "Rank" in rendered
    assert "MI26RYRR" in rendered
    assert "Mantle hydration" in rendered


def test_table_render_list_of_objects() -> None:
    payload = [
        {"key": "A", "name": "Geophysics"},
        {"key": "B", "name": "ML"},
    ]

    rendered = render_payload(payload, OutputFormat.TABLE)
    assert "key" in rendered
    assert "name" in rendered
    assert "Geophysics" in rendered
    assert "ML" in rendered


def test_table_render_key_value_payload() -> None:
    payload = {"status": "ok", "mode": "local-api", "adapter": "local-api"}

    rendered = render_payload(payload, OutputFormat.TABLE)
    assert "Key" in rendered
    assert "Value" in rendered
    assert "status" in rendered
    assert "local-api" in rendered
