"""Render command results as a table, JSON, NDJSON, or CSV."""

from __future__ import annotations

import csv
import io
import json
import sys
from typing import Any

from gdocs.errors import GdocsError

_FORMATS = {"table", "json", "ndjson", "csv", "plain"}
_CLIP = 40


def choose_output(explicit: str | None, isatty: bool) -> str:
    if explicit is None:
        from gdocs.preferences import load
        explicit = load().get("output")
    if explicit is None:
        return "table" if isatty else "json"
    if explicit not in _FORMATS:
        raise GdocsError("output must be table, json, ndjson, or csv")
    return explicit


def emit(data: Any, explicit: str | None, columns: list[str] | None = None) -> None:
    fmt = choose_output(explicit, sys.stdout.isatty())
    sys.stdout.write(render(data, fmt, columns=columns))


def render(data: Any, fmt: str, columns: list[str] | None = None) -> str:
    if fmt not in _FORMATS:
        raise GdocsError("output must be table, json, ndjson, or csv")
    if fmt == "plain":
        return plain(data) + "\n"
    if isinstance(data, dict):
        if fmt == "json":
            return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        rows: list[Any] = [data]
    elif isinstance(data, list):
        rows = data
    else:
        raise GdocsError("nothing to print")
    if not rows:
        if fmt == "json":
            return "[]\n"
        if fmt == "ndjson":
            return ""
        if fmt == "csv":
            return ""
        return ""
    if not isinstance(rows[0], dict):
        return _render_lists(rows, fmt)
    return _render_dicts(rows, fmt, columns)


def _render_lists(rows: list[Any], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
    if fmt == "ndjson":
        return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for row in rows:
            writer.writerow(row if isinstance(row, list) else [row])
        return buffer.getvalue()
    width = max(len(row) for row in rows if isinstance(row, list))
    return _draw([[_clip(cell) for cell in _pad_list(row, width)] for row in rows])


def _render_dicts(rows: list[dict[str, Any]], fmt: str, columns: list[str] | None) -> str:
    cols = columns or _columns(rows)
    if fmt == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
    if fmt == "ndjson":
        return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in cols})
        return buffer.getvalue()
    drawn = [[_clip(key) for key in cols]]
    for row in rows:
        drawn.append([_clip(row.get(key, "")) for key in cols])
    return _draw(drawn)


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen


def _pad_list(row: Any, width: int) -> list[Any]:
    if not isinstance(row, list):
        row = [row]
    return list(row) + [""] * (width - len(row))


def _clip(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ")
    if len(text) > _CLIP:
        return text[: _CLIP - 1] + "…"
    return text


def _draw(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    widths = [0] * len(rows[0])
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = []
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)).rstrip())
    return "\n".join(lines) + "\n"


def plain(data):
    if isinstance(data, dict):
        return "\n".join(f"{key}: {plain(value)}" for key, value in data.items())
    if isinstance(data, list):
        return "\n\n".join(f"Record {i}:\n{plain(value)}" for i, value in enumerate(data, 1)) or "No records."
    return "" if data is None else str(data)
