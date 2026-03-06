from __future__ import annotations

import json
import tempfile

import pytest
import respx
from click.testing import CliRunner
from httpx import Response

from zotq.cli import main


@pytest.mark.parametrize(
    ("mode", "base_url", "root"),
    [
        ("local-api", "http://local.test", "http://local.test/api/users/0"),
        ("remote", "http://remote.test", "http://remote.test/users/0"),
    ],
)
@respx.mock
def test_cli_search_paged_mixed_types(mode: str, base_url: str, root: str) -> None:
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
        ]
    )

    env = {
        "ZOTQ_MODE": mode,
        "ZOTQ_LOCAL_API_BASE_URL": base_url,
        "ZOTQ_REMOTE_BASE_URL": base_url,
        "ZOTQ_INDEX_DIR": tempfile.mkdtemp(prefix="zotq-test-e2e-index-"),
    }

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--output",
            "json",
            "search",
            "run",
            "mantle",
            "--item-type",
            "journalArticle",
            "--limit",
            "2",
        ],
        env=env,
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total"] == 2
    assert [hit["item"]["key"] for hit in payload["hits"]] == ["MI26RYRR", "XJP5WU22"]
