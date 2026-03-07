from __future__ import annotations

import importlib


def test_bibtexparser_dependency_imports() -> None:
    assert importlib.import_module("bibtexparser") is not None


def test_sqlite_vec_dependency_imports() -> None:
    assert importlib.import_module("sqlite_vec") is not None
