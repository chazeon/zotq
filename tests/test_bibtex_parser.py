from __future__ import annotations

from zotq.bibtex_parser import (
    bibtex_citation_key,
    bibtex_citation_keys,
    canonicalize_bibtex_text,
    canonicalize_bibtex_texts,
)
from zotq.models import OutputFormat
from zotq.output import render_payload


def test_bibtex_citation_key_returns_first_entry_key() -> None:
    text = "@comment{ignored}\n@article{RealKey,\n  title={X}\n}\n"
    assert bibtex_citation_key(text) == "RealKey"


def test_bibtex_citation_keys_ignores_non_entry_blocks() -> None:
    text = (
        "@preamble{\"ignored\"}\n"
        "@comment{alsoIgnored}\n"
        "@article{Alpha,\n  title={A}\n}\n\n"
        "@book{Beta,\n  title={B}\n}\n"
    )
    assert bibtex_citation_keys(text) == ["Alpha", "Beta"]


def test_canonicalize_bibtex_text_deterministic_order_and_format() -> None:
    text = (
        "@book{Beta,\n  title={B},\n  year={2020}\n}\n\n"
        "@article{Alpha,\n  title={A},\n  year={2019}\n}\n"
    )
    rendered = canonicalize_bibtex_text(text)

    assert rendered is not None
    assert rendered.index("@article{Alpha,") < rendered.index("@book{Beta,")
    assert "  title = {A}" in rendered
    assert "  year = {2019}" in rendered


def test_canonicalize_bibtex_texts_merges_and_sorts_entries() -> None:
    out = canonicalize_bibtex_texts(
        [
            "@book{Beta,\n  title={B}\n}\n",
            "@article{Alpha,\n  title={A}\n}\n",
        ]
    )
    assert out.index("@article{Alpha,") < out.index("@book{Beta,")


def test_render_payload_bibtex_applies_canonical_policy_for_list_inputs() -> None:
    payload = [
        "@book{Beta,\n  title={B}\n}\n",
        "@article{Alpha,\n  title={A}\n}\n",
    ]
    rendered = render_payload(payload, OutputFormat.BIBTEX)

    assert rendered.index("@article{Alpha,") < rendered.index("@book{Beta,")
