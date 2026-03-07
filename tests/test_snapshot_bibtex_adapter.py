from __future__ import annotations

from pathlib import Path

from zotq.models import AppConfig, Mode, QuerySpec, SearchMode
from zotq.sources.snapshot_bibtex import BibtexSnapshotSourceAdapter


def _write_snapshot(path: Path) -> Path:
    bib_path = path / "library.bib"
    bib_path.write_text(
        """
@article{nishiMantleHydration2015,
  title = {Mantle hydration},
  author = {Nishi, Masayuki and Bell, David R.},
  year = {2015},
  doi = {10.1234/mantle.2015},
  journal = {Geophysical Journal},
  keywords = {mantle, hydration}
}

@article{staceyThermodynamics2019,
  title = {Thermodynamics with the Gruneisen parameter},
  author = {Stacey, Frank D.},
  year = {2019},
  doi = {10.1016/j.pepi.2018.10.006},
  journal = {Physics of the Earth and Planetary Interiors},
  keywords = {thermodynamics, planetary interiors}
}
""".strip()
    )
    return bib_path


def _build_adapter(bib_path: Path) -> BibtexSnapshotSourceAdapter:
    config = AppConfig()
    profile = config.profiles["default"]
    profile.mode = Mode.SNAPSHOT
    profile.snapshot.bib_path = str(bib_path)
    return BibtexSnapshotSourceAdapter(profile)


def test_snapshot_adapter_health_and_capabilities(tmp_path: Path) -> None:
    adapter = _build_adapter(_write_snapshot(tmp_path))

    health = adapter.health()
    caps = adapter.capabilities()

    assert health["status"] == "ok"
    assert health["adapter"] == "snapshot-bibtex"
    assert caps.keyword is True
    assert caps.fuzzy is True
    assert caps.semantic is False
    assert caps.hybrid is False


def test_snapshot_adapter_search_supports_doi_and_citation_key_normalization(tmp_path: Path) -> None:
    adapter = _build_adapter(_write_snapshot(tmp_path))
    hits = adapter.search_items(
        QuerySpec(
            search_mode=SearchMode.KEYWORD,
            doi="https://doi.org/10.1016/j.pepi.2018.10.006",
            citation_key="staceythermodynamics2019",
            journal="planetary interiors",
            limit=10,
            offset=0,
        )
    )

    assert len(hits) == 1
    assert hits[0].item.key == "staceyThermodynamics2019"


def test_snapshot_adapter_bibtex_roundtrip_methods(tmp_path: Path) -> None:
    adapter = _build_adapter(_write_snapshot(tmp_path))

    one = adapter.get_item_bibtex("nishiMantleHydration2015")
    many = adapter.get_items_bibtex(["nishiMantleHydration2015", "staceyThermodynamics2019"])
    citekeys = adapter.get_items_citation_keys_rpc(["nishiMantleHydration2015", "MISSING"])

    assert one is not None
    assert "@article{nishiMantleHydration2015" in one
    assert many is not None
    assert "@article{nishiMantleHydration2015" in many
    assert "@article{staceyThermodynamics2019" in many
    assert citekeys == {"nishiMantleHydration2015": "nishiMantleHydration2015"}
