"""Output rendering helpers."""

from __future__ import annotations

from io import StringIO
import json
from typing import Any

from rich.console import Console
from rich.table import Table

from .models import OutputFormat


def _json_default(value: Any) -> str:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Object is not JSON serializable: {type(value)!r}")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=_json_default, ensure_ascii=False)
    return str(value)


def _console_to_text(*renderables: Any) -> str:
    sink = StringIO()
    console = Console(
        file=sink,
        record=True,
        width=120,
        force_terminal=False,
        color_system=None,
        highlight=False,
    )
    for renderable in renderables:
        console.print(renderable)
    return console.export_text().rstrip("\n")


def _render_key_value_table(payload: dict[str, Any], *, title: str | None = None) -> Table:
    table = Table(title=title)
    table.add_column("Key")
    table.add_column("Value")
    for key, value in payload.items():
        table.add_row(str(key), _stringify(value))
    return table


def _render_objects_table(payload: list[dict[str, Any]], *, title: str | None = None) -> Table:
    columns: list[str] = []
    for row in payload:
        for key in row.keys():
            if key not in columns:
                columns.append(str(key))

    table = Table(title=title)
    for column in columns:
        table.add_column(column)

    for row in payload:
        values = [_stringify(row.get(column)) for column in columns]
        table.add_row(*values)

    return table


def _render_search_payload(payload: dict[str, Any]) -> str:
    summary = Table(title="Search Summary")
    summary.add_column("Field")
    summary.add_column("Value")
    summary.add_row("Requested Mode", _stringify(payload.get("requested_mode")))
    summary.add_row("Executed Mode", _stringify(payload.get("executed_mode")))
    summary.add_row("Total", _stringify(payload.get("total")))
    summary.add_row("Limit", _stringify(payload.get("limit")))
    summary.add_row("Offset", _stringify(payload.get("offset")))

    hits_table = Table(title="Hits")
    hits_table.add_column("Rank")
    hits_table.add_column("Key")
    hits_table.add_column("Type")
    hits_table.add_column("Date")
    hits_table.add_column("Score")
    hits_table.add_column("Title")

    hits = payload.get("hits")
    if isinstance(hits, list):
        for rank, hit in enumerate(hits, start=1):
            if not isinstance(hit, dict):
                continue
            item = hit.get("item")
            item_dict = item if isinstance(item, dict) else {}
            score = hit.get("score")
            if isinstance(score, (int, float)):
                score_text = f"{float(score):.6g}"
            else:
                score_text = _stringify(score)
            hits_table.add_row(
                str(rank),
                _stringify(item_dict.get("key")),
                _stringify(item_dict.get("item_type")),
                _stringify(item_dict.get("date")),
                score_text,
                _stringify(item_dict.get("title")),
            )

    renderables: list[Any] = [summary, hits_table]
    debug = payload.get("debug")
    if isinstance(debug, dict):
        renderables.append(_render_key_value_table({k: v for k, v in debug.items() if k != "hits"}, title="Debug"))
        debug_hits = debug.get("hits")
        if isinstance(debug_hits, list):
            debug_rows = [row for row in debug_hits if isinstance(row, dict)]
            if debug_rows:
                renderables.append(_render_objects_table(debug_rows, title="Debug Hits"))
    return _console_to_text(*renderables)


def _render_table(payload: Any) -> str:
    if isinstance(payload, dict):
        if isinstance(payload.get("hits"), list) and "executed_mode" in payload and "requested_mode" in payload:
            return _render_search_payload(payload)

        item = payload.get("item")
        found = payload.get("found")
        if isinstance(found, bool) and (isinstance(item, dict) or item is None):
            summary = _render_key_value_table({"found": found}, title="Item")
            if isinstance(item, dict):
                details = _render_key_value_table(item, title="Item Fields")
                return _console_to_text(summary, details)
            return _console_to_text(summary)

        return _console_to_text(_render_key_value_table(payload))

    if isinstance(payload, list):
        if payload and all(isinstance(item, dict) for item in payload):
            return _console_to_text(_render_objects_table(payload))
        table = Table()
        table.add_column("Value")
        for item in payload:
            table.add_row(_stringify(item))
        return _console_to_text(table)

    return _stringify(payload)


def render_payload(payload: Any, output_format: OutputFormat) -> str:
    if output_format == OutputFormat.JSON:
        return json.dumps(payload, indent=2, default=_json_default)

    if output_format == OutputFormat.JSONL:
        if isinstance(payload, list):
            return "\n".join(json.dumps(item, default=_json_default) for item in payload)
        return json.dumps(payload, default=_json_default)

    return _render_table(payload)
