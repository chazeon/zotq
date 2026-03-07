from __future__ import annotations

import pytest
import respx
from httpx import Response

from zotq.models import AppConfig, Mode, QuerySpec, SearchMode
from zotq.sources.local_api import LocalApiSourceAdapter
from zotq.sources.remote_api import RemoteApiSourceAdapter


def _build_local() -> LocalApiSourceAdapter:
    config = AppConfig()
    profile = config.profiles["default"]
    profile.mode = Mode.LOCAL_API
    profile.local_api.base_url = "http://local.test"
    profile.local_api.library_id = "0"
    return LocalApiSourceAdapter(profile)


def _build_remote() -> RemoteApiSourceAdapter:
    config = AppConfig()
    profile = config.profiles["default"]
    profile.mode = Mode.REMOTE
    profile.remote.base_url = "http://remote.test"
    profile.remote.library_id = "0"
    profile.remote.bearer_token = "token"
    return RemoteApiSourceAdapter(profile)


@pytest.mark.parametrize(
    ("builder", "root"),
    [
        (_build_local, "http://local.test/api/users/0"),
        (_build_remote, "http://remote.test/users/0"),
    ],
)
@respx.mock
def test_health_and_get_item_contract(builder, root: str) -> None:
    respx.get(f"{root}/items", params={"limit": 1}).mock(return_value=Response(200, json=[]))
    respx.get(f"{root}/items/MI26RYRR").mock(
        return_value=Response(
            200,
            json={
                "key": "MI26RYRR",
                "data": {
                    "itemType": "journalArticle",
                    "title": "Mantle hydration",
                    "date": "2015",
                    "creators": [{"firstName": "Masayuki", "lastName": "Nishi"}],
                    "tags": [{"tag": "mantle"}],
                },
            },
        )
    )

    adapter = builder()

    health = adapter.health()
    item = adapter.get_item("MI26RYRR")

    assert health["status"] == "ok"
    assert item is not None
    assert item.key == "MI26RYRR"
    assert item.title == "Mantle hydration"


@pytest.mark.parametrize(
    ("builder", "root"),
    [
        (_build_local, "http://local.test/api/users/0"),
        (_build_remote, "http://remote.test/users/0"),
    ],
)
@respx.mock
def test_get_item_404_returns_none(builder, root: str) -> None:
    respx.get(f"{root}/items/MISSING").mock(return_value=Response(404, json={}))

    adapter = builder()
    assert adapter.get_item("MISSING") is None


@pytest.mark.parametrize(
    ("builder", "root"),
    [
        (_build_local, "http://local.test/api/users/0"),
        (_build_remote, "http://remote.test/users/0"),
    ],
)
@respx.mock
def test_search_contract_filters_consistently(builder, root: str) -> None:
    respx.get(f"{root}/items").mock(
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

    adapter = builder()
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


@pytest.mark.parametrize(
    ("builder", "root"),
    [
        (_build_local, "http://local.test/api/users/0"),
        (_build_remote, "http://remote.test/users/0"),
    ],
)
@respx.mock
def test_search_contract_paginates_and_filters_mixed_types(builder, root: str) -> None:
    page2 = f"{root}/items?limit=100&start=100"

    respx.get(f"{root}/items").mock(
        side_effect=[
            Response(
                200,
                headers={"Link": f"<{page2}>; rel=\"next\""},
                json=[
                    {
                        "key": "NOTE1",
                        "data": {
                            "itemType": "note",
                            "title": "Working note",
                            "date": "2023",
                            "creators": [],
                            "tags": [{"tag": "mantle"}],
                        },
                    },
                    {
                        "key": "MI26RYRR",
                        "data": {
                            "itemType": "journalArticle",
                            "title": "Mantle hydration",
                            "date": "2015",
                            "creators": [{"firstName": "Masayuki", "lastName": "Nishi"}],
                            "tags": [{"tag": "mantle"}],
                        },
                    },
                ],
            ),
            Response(
                200,
                json=[
                    {
                        "key": "XJP5WU22",
                        "data": {
                            "itemType": "journalArticle",
                            "title": "Water in Earth's Mantle",
                            "date": "1992",
                            "creators": [{"firstName": "David", "lastName": "Bell"}],
                            "tags": [{"tag": "mantle"}],
                        },
                    }
                ],
            ),
        ],
    )

    adapter = builder()
    hits = adapter.search_items(
        QuerySpec(
            text="mantle",
            search_mode=SearchMode.KEYWORD,
            item_type="journalArticle",
            limit=2,
            offset=0,
        )
    )

    assert len(hits) == 2
    assert [h.item.key for h in hits] == ["MI26RYRR", "XJP5WU22"]


@pytest.mark.parametrize(
    ("builder", "root"),
    [
        (_build_local, "http://local.test/api/users/0"),
        (_build_remote, "http://remote.test/users/0"),
    ],
)
@respx.mock
def test_search_contract_filters_doi_journal_and_citation_key(builder, root: str) -> None:
    respx.get(f"{root}/items").mock(
        return_value=Response(
            200,
            json=[
                {
                    "key": "XVMVWQZX",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Thermodynamics with the Gruneisen parameter",
                        "date": "2019",
                        "DOI": "10.1016/j.pepi.2018.10.006",
                        "publicationTitle": "Physics of the Earth and Planetary Interiors",
                        "citationKey": "staceyThermodynamicsGruneisenParameter2019",
                    },
                },
                {
                    "key": "MI26RYRR",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Mantle hydration",
                        "date": "2015",
                        "DOI": "10.1234/example",
                        "publicationTitle": "Geophysical Journal",
                        "citationKey": "nishi2015mantle",
                    },
                },
            ],
        )
    )

    adapter = builder()
    hits = adapter.search_items(
        QuerySpec(
            search_mode=SearchMode.KEYWORD,
            doi="https://doi.org/10.1016/j.pepi.2018.10.006",
            journal="planetary interiors",
            citation_key="staceythermodynamicsgruneisenparameter2019",
            limit=20,
            offset=0,
        )
    )

    assert len(hits) == 1
    assert hits[0].item.key == "XVMVWQZX"
