from __future__ import annotations

import respx
from httpx import Response

from zotq.models import AppConfig, Mode, QuerySpec, SearchMode
from zotq.sources.local_api import LocalApiSourceAdapter


def build_local_adapter() -> LocalApiSourceAdapter:
    config = AppConfig()
    profile = config.profiles["default"]
    profile.mode = Mode.LOCAL_API
    profile.local_api.base_url = "http://zotero.test"
    profile.local_api.library_id = "0"
    profile.local_api.timeout_seconds = 5
    return LocalApiSourceAdapter(profile)


@respx.mock
def test_health_calls_local_api() -> None:
    respx.get("http://zotero.test/api/users/0/items").mock(return_value=Response(200, json=[]))

    adapter = build_local_adapter()
    payload = adapter.health()

    assert payload["status"] == "ok"
    assert payload["adapter"] == "local-api"


@respx.mock
def test_get_item_parses_zotero_payload() -> None:
    respx.get("http://zotero.test/api/users/0/items/MI26RYRR").mock(
        return_value=Response(
            200,
            json={
                "key": "MI26RYRR",
                "data": {
                    "itemType": "journalArticle",
                    "title": "Mantle hydration",
                    "date": "2015",
                    "abstractNote": "summary",
                    "creators": [{"firstName": "Masayuki", "lastName": "Nishi"}],
                    "tags": [{"tag": "mantle"}],
                },
            },
        )
    )

    adapter = build_local_adapter()
    item = adapter.get_item("MI26RYRR")

    assert item is not None
    assert item.key == "MI26RYRR"
    assert item.title == "Mantle hydration"
    assert item.item_type == "journalArticle"
    assert item.tags == ["mantle"]


@respx.mock
def test_get_item_returns_none_on_404() -> None:
    respx.get("http://zotero.test/api/users/0/items/MISSING").mock(return_value=Response(404, json={}))

    adapter = build_local_adapter()
    item = adapter.get_item("MISSING")

    assert item is None


@respx.mock
def test_list_collections_and_tags_parse_payloads() -> None:
    respx.get("http://zotero.test/api/users/0/collections").mock(
        return_value=Response(
            200,
            json=[
                {"key": "AAA", "data": {"name": "Geophysics", "parentCollection": None}},
                {"key": "BBB", "data": {"name": "AI", "parentCollection": "AAA"}},
            ],
        )
    )
    respx.get("http://zotero.test/api/users/0/tags").mock(
        return_value=Response(
            200,
            json=[{"tag": "mantle", "type": 0}, {"tag": "water", "type": 0}],
        )
    )

    adapter = build_local_adapter()
    collections = adapter.list_collections()
    tags = adapter.list_tags()

    assert [c.name for c in collections] == ["Geophysics", "AI"]
    assert tags[0].tag == "mantle"


@respx.mock
def test_search_items_applies_filters_after_api_query() -> None:
    respx.get("http://zotero.test/api/users/0/items").mock(
        return_value=Response(
            200,
            json=[
                {
                    "key": "MI26RYRR",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Mantle hydration",
                        "date": "2015",
                        "creators": [{"firstName": "Masayuki", "lastName": "Nishi"}],
                        "tags": [{"tag": "mantle"}, {"tag": "hydration"}],
                    },
                },
                {
                    "key": "XJP5WU22",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Water in Earth's Mantle",
                        "date": "1992",
                        "creators": [{"firstName": "David", "lastName": "Bell"}],
                        "tags": [{"tag": "mantle"}],
                    },
                },
            ],
        )
    )

    adapter = build_local_adapter()
    hits = adapter.search_items(
        QuerySpec(
            text="mantle",
            search_mode=SearchMode.KEYWORD,
            creators=["Nishi"],
            year_from=2010,
            tags=["hydration"],
            limit=20,
            offset=0,
        )
    )

    assert len(hits) == 1
    assert hits[0].item.key == "MI26RYRR"
