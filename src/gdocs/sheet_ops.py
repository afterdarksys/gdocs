"""Sheets reads and cell, row, and column edits.

Threats: a delete is refused before a client is built. Values are bounded
before a write. ``--formula`` is sent as USER_ENTERED and ``--raw`` as RAW.
Does not evaluate formulas locally or open ``.xlsx`` files.
"""

from __future__ import annotations

from pathlib import Path

from gdocs.drive_ops import abandon, check_title, create_file, open_drive, resolve
from gdocs.errors import GdocsError
from gdocs.filesafe import check_import_file, read_text_input
from gdocs.grid import (
    MAX_VALUES_BYTES,
    apply_set,
    assert_cell_budget,
    column_index,
    column_letter,
    content_limit,
    check_tab_title,
    grid_from_records,
    header_list,
    matching_sheet_rows,
    objects_to_grid,
    parse_cell,
    parse_columns,
    parse_csv_text,
    parse_json_payload,
    parse_sets,
    parse_where,
    rows_for_header,
    plan_basic_filter,
    plan_copy_column,
    plan_delete,
    plan_insert,
    qualify_range,
    quote_sheet_name,
    records_from_grid,
    require_match_count,
    resolve_column,
    value_input_option,
)
from gdocs.grid import _check_cell

_ALL_MATCH_CAP = 500
_META_FIELDS = "properties.title,sheets.properties"


def view(target: str, *, tab: str | None = None, head: int | None = None, raw: bool = False, limit: int | None = None):
    _check_head(head)
    content_limit(limit)
    creds, meta, sheet = _open(target, write=False, tab=tab)
    grid = _load_grid(creds, meta["id"], sheet["title"], raw=raw, limit=limit, strict=False)
    if head is not None:
        grid = grid[:head]
    return grid


def update(
    target: str,
    range_a1: str | None,
    *,
    values: str | None,
    json_path: str | None,
    append: bool,
    raw: bool,
    formula: bool,
    tab: str | None,
) -> dict:
    option = value_input_option(raw=raw, formula=formula)
    if not append and not range_a1:
        raise GdocsError("update needs a range or --append")
    _reject_range_text(range_a1)
    kind, payload = _payload(values, json_path)
    if kind == "grid":
        assert_cell_budget(payload)
    creds, meta, sheet = _open(target, write=True, tab=tab)
    grid = _grid_from_payload(creds, meta["id"], sheet["title"], kind, payload)
    assert_cell_budget(grid)
    target_range = qualify_range(sheet["title"], range_a1 or ("A1" if append else None))
    if append:
        response = _values_call(
            creds,
            "append",
            meta["id"],
            target_range,
            option,
            {"values": grid},
            insert_data_option="INSERT_ROWS",
        )
        _require_cells(response, nested=True)
    else:
        response = _values_call(creds, "update", meta["id"], target_range, option, {"values": grid})
        _require_cells(response)
    return {"id": meta["id"], "updated": True}


def edit_cell(
    target: str,
    *,
    cell: str,
    value: str | None,
    formula: str | None,
    raw: bool,
    tab: str | None,
) -> dict:
    option = value_input_option(raw=raw, formula=formula)
    text = _one_cell(value, formula)
    column, row = parse_cell(cell)
    assert_cell_budget([[text]])
    creds, meta, sheet = _open(target, write=True, tab=tab)
    letter = column_letter(column)
    target_range = qualify_range(sheet["title"], f"{letter}{row}")
    response = _values_call(creds, "update", meta["id"], target_range, option, {"values": [[text]]})
    _require_cells(response)
    return {"id": meta["id"], "updated": True}


def edit_row(
    target: str,
    *,
    row: int | None,
    values: str | None,
    json_path: str | None,
    where: str | None,
    sets: list[str] | None,
    insert: int | None,
    delete: int | None,
    all_matches: bool,
    yes: bool,
    raw: bool,
    formula: bool,
    tab: str | None,
    limit: int | None,
) -> dict:
    if delete is not None and not yes:
        plan_delete(0, "ROWS", delete, False)
    option = value_input_option(raw=raw, formula=formula)
    mode = _row_mode(row, values, json_path, where, sets, insert, delete)
    if mode == "delete":
        creds, meta, sheet = _open(target, write=True, tab=tab)
        request = plan_delete(sheet["sheetId"], "ROWS", delete, True)
        _batch(creds, meta["id"], [request])
        return {"id": meta["id"], "deleted": True}
    if mode == "insert":
        _check_displayed(insert, "row number is invalid")
        creds, meta, sheet = _open(target, write=True, tab=tab)
        request = plan_insert(sheet["sheetId"], "ROWS", insert)
        _batch(creds, meta["id"], [request])
        return {"id": meta["id"], "inserted": True}
    if mode == "values":
        if row is None or (values is None and json_path is None):
            raise GdocsError("row values need --row and --values or --json")
        _check_displayed(row, "row number is invalid")
        kind, payload = _payload(values, json_path)
        if kind == "grid":
            grid = payload
            assert_cell_budget(grid)
        else:
            grid = None
        creds, meta, sheet = _open(target, write=True, tab=tab)
        if grid is None:
            grid = _grid_from_payload(creds, meta["id"], sheet["title"], kind, payload)
            assert_cell_budget(grid)
        if len(grid) != 1:
            raise GdocsError("row values must be one row")
        target_range = qualify_range(sheet["title"], f"A{row}")
        response = _values_call(creds, "update", meta["id"], target_range, option, {"values": grid})
        _require_cells(response)
        return {"id": meta["id"], "updated": True}
    if not where or not sets:
        raise GdocsError("where edits need --where and --set")
    clauses = parse_where(where)
    parsed = parse_sets(sets)
    match_limit = _match_limit(all_matches, limit)
    creds, meta, sheet = _open(target, write=True, tab=tab)
    existing = _load_grid(creds, meta["id"], sheet["title"], raw=False, limit=None, strict=True)
    headers = header_list(existing)
    matched = require_match_count(matching_sheet_rows(existing, clauses), all_matches, match_limit)
    data = []
    for sheet_row in matched:
        source = existing[sheet_row - 1] if sheet_row - 1 < len(existing) else []
        updated = apply_set(source, headers, parsed)
        data.append({"range": qualify_range(sheet["title"], f"A{sheet_row}"), "values": [updated]})
    assert_cell_budget([item["values"][0] for item in data])
    response = _batch_values(creds, meta["id"], option, data)
    _require_total(response)
    return {"id": meta["id"], "updated": True}


def edit_col(
    target: str,
    *,
    col: str | None,
    source: str | None,
    values: str | None,
    json_path: str | None,
    insert: bool,
    at: str | None,
    header: str | None,
    delete: bool,
    rename: str | None,
    yes: bool,
    raw: bool,
    formula: bool,
    tab: str | None,
) -> dict:
    if delete and not yes:
        plan_delete(0, "COLUMNS", 1, False)
    option = value_input_option(raw=raw, formula=formula)
    mode = _col_mode(source, values, json_path, insert, at, header, delete, rename)
    if mode == "delete":
        if not col:
            raise GdocsError("missing --col")
        creds, meta, sheet = _open(target, write=True, tab=tab)
        headers = header_list(_header_row(creds, meta["id"], sheet["title"]))
        index = resolve_column(col, headers)
        request = plan_delete(sheet["sheetId"], "COLUMNS", index + 1, True)
        _batch(creds, meta["id"], [request])
        return {"id": meta["id"], "deleted": True}
    if mode == "insert":
        if not at:
            raise GdocsError("insert needs --at")
        displayed = column_index(at) + 1
        creds, meta, sheet = _open(target, write=True, tab=tab)
        request = plan_insert(sheet["sheetId"], "COLUMNS", displayed)
        _batch(creds, meta["id"], [request])
        if header is not None:
            _write_header(creds, meta["id"], sheet["title"], at, header, option)
        return {"id": meta["id"], "inserted": True}
    if not col:
        raise GdocsError("missing --col")
    creds, meta, sheet = _open(target, write=True, tab=tab)
    existing = _load_grid(creds, meta["id"], sheet["title"], raw=False, limit=None, strict=True)
    headers = header_list(existing)
    if mode == "rename":
        return _rename_column(creds, meta["id"], sheet["title"], headers, col, rename or "", option)
    if mode == "from":
        column = plan_copy_column(existing, col, source or "")
        dest = resolve_column(col, headers)
    else:
        column = _column_payload(values, json_path)
        dest = resolve_column(col, headers)
        _reject_same_column(existing, dest, column)
    assert_cell_budget(column)
    letter = column_letter(dest)
    end_row = 1 + len(column)
    target_range = qualify_range(sheet["title"], f"{letter}2:{letter}{end_row}")
    response = _values_call(creds, "update", meta["id"], target_range, option, {"values": column})
    _require_cells(response)
    return {"id": meta["id"], "updated": True}


def filter_sheet(target: str, *, where: str, apply: bool, tab: str | None, limit: int | None):
    clauses = parse_where(where)
    if not apply:
        content_limit(limit)
        creds, meta, sheet = _open(target, write=False, tab=tab)
        grid = _load_grid(creds, meta["id"], sheet["title"], raw=False, limit=limit, strict=False)
        return filter_rows_local(grid, clauses)
    creds, meta, sheet = _open(target, write=True, tab=tab)
    headers = header_list(_header_row(creds, meta["id"], sheet["title"]))
    request = plan_basic_filter(sheet["sheetId"], headers, clauses)
    _batch(creds, meta["id"], [request])
    return {"id": meta["id"], "applied": True}


def extract(target: str, *, cols: str, where: str | None, tab: str | None, limit: int | None):
    tokens = _column_tokens(cols)
    clauses = parse_where(where) if where else None
    content_limit(limit)
    creds, meta, sheet = _open(target, write=False, tab=tab)
    grid = _load_grid(creds, meta["id"], sheet["title"], raw=False, limit=limit, strict=False)
    if not grid:
        return []
    headers = header_list(grid)
    selected = grid
    if clauses:
        matched = matching_sheet_rows(grid, clauses)
        selected = [grid[0]] + [grid[index - 1] for index in matched if index - 1 < len(grid)]
    labels: list[str] = []
    indexes: list[int] = []
    for token in tokens:
        index = resolve_column(token, headers)
        label = headers[index] if index < len(headers) and headers[index] else token
        if label in labels:
            raise GdocsError(f"duplicate column {label}")
        labels.append(label)
        indexes.append(index)
    rows = []
    for record in selected[1:]:
        rows.append({label: record[index] if index < len(record) else "" for label, index in zip(labels, indexes)})
    return rows


def as_json(target: str, *, tab: str | None, limit: int | None):
    content_limit(limit)
    creds, meta, sheet = _open(target, write=False, tab=tab)
    grid = _load_grid(creds, meta["id"], sheet["title"], raw=False, limit=limit, strict=False)
    return records_from_grid(grid)


def import_csv(target: str, path: str, *, tab: str | None, replace: bool) -> dict:
    source = Path(path)
    if source.suffix.lower() != ".csv":
        raise GdocsError("csv import needs a .csv file")
    if not replace:
        raise GdocsError("--replace is required")
    check_import_file(source)
    grid = parse_csv_text(read_text_input(str(source), MAX_VALUES_BYTES))
    assert_cell_budget(grid)
    creds, meta, sheet = _open(target, write=True, tab=tab)
    _values_call(creds, "clear", meta["id"], quote_sheet_name(sheet["title"]), "USER_ENTERED", {})
    _values_call(
        creds,
        "update",
        meta["id"],
        qualify_range(sheet["title"], "A1"),
        "USER_ENTERED",
        {"values": grid},
    )
    return {"id": meta["id"], "replaced": True, "rows": len(grid)}


def filter_rows_local(grid, clauses):
    from gdocs.grid import filter_rows

    return filter_rows(grid, clauses)


def _open(target: str, *, write: bool, tab: str | None):
    from gdocs import services

    creds, drive = open_drive(write=write)
    meta = resolve(drive, "sheet", target)
    book = services.execute(
        _sheets(creds).spreadsheets().get(spreadsheetId=meta["id"], fields=_META_FIELDS)
    )
    return creds, meta, _pick_tab(book, tab)


def _sheets(creds):
    from gdocs import services

    return services.build("sheets", "v4", creds)


def _pick_tab(book: dict, tab: str | None) -> dict:
    props = []
    for item in book.get("sheets") or []:
        prop = item.get("properties") or {}
        if isinstance(prop, dict):
            props.append(prop)
    if tab:
        matches = [prop for prop in props if prop.get("title") == tab]
        if not matches:
            raise GdocsError("sheet tab was not found")
        if len(matches) > 1:
            raise GdocsError("sheet tab name matches more than one tab")
        chosen = matches[0]
    elif not props:
        raise GdocsError("sheet tab was not found")
    else:
        chosen = props[0]
    sheet_id = chosen.get("sheetId")
    if isinstance(sheet_id, bool) or not isinstance(sheet_id, int):
        raise GdocsError("sheet id is invalid")
    title = chosen.get("title")
    if not isinstance(title, str) or title == "":
        raise GdocsError("sheet name is missing")
    return {"sheetId": sheet_id, "title": title}


def _load_grid(creds, spreadsheet_id: str, title: str, *, raw: bool, limit: int | None, strict: bool):
    grid = _stringify(_values_get(creds, spreadsheet_id, qualify_range(title, None), raw=raw))
    cap = content_limit(None if strict else limit)
    if len(grid) > cap:
        if strict:
            raise GdocsError("sheet exceeds 20000 rows")
        return grid[:cap]
    return grid


def _header_row(creds, spreadsheet_id: str, title: str):
    return _stringify(_values_get(creds, spreadsheet_id, qualify_range(title, "1:1"), raw=False))


def _values_get(creds, spreadsheet_id: str, range_a1: str, *, raw: bool):
    from gdocs import services

    option = "FORMULA" if raw else "FORMATTED_VALUE"
    return services.execute(
        _sheets(creds).spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_a1,
            valueRenderOption=option,
        )
    ).get("values") or []


def _values_call(creds, method: str, spreadsheet_id: str, range_a1: str, option: str, body: dict, insert_data_option: str | None = None):
    from gdocs import services

    values = _sheets(creds).spreadsheets().values()
    if method == "clear":
        request = values.clear(spreadsheetId=spreadsheet_id, range=range_a1, body=body)
    elif method == "append":
        request = values.append(
            spreadsheetId=spreadsheet_id,
            range=range_a1,
            valueInputOption=option,
            insertDataOption=insert_data_option,
            body=body,
        )
    else:
        request = values.update(
            spreadsheetId=spreadsheet_id,
            range=range_a1,
            valueInputOption=option,
            body=body,
        )
    return services.execute(request)


def _batch(creds, spreadsheet_id: str, requests: list[dict]) -> dict:
    from gdocs import services

    return services.execute(
        _sheets(creds).spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests})
    )


def _batch_values(creds, spreadsheet_id: str, option: str, data: list[dict]) -> dict:
    from gdocs import services

    return services.execute(
        _sheets(creds).spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": option, "data": data},
        )
    )


def _write_header(creds, spreadsheet_id: str, title: str, letter: str, header: str, option: str) -> None:
    text = _check_cell(header)
    if text == "":
        raise GdocsError("column name is missing")
    assert_cell_budget([[text]])
    response = _values_call(
        creds,
        "update",
        spreadsheet_id,
        qualify_range(title, f"{letter}1"),
        option,
        {"values": [[text]]},
    )
    _require_cells(response)


def _rename_column(creds, spreadsheet_id: str, title: str, headers: list[str], col: str, new_name: str, option: str) -> dict:
    index = resolve_column(col, headers)
    text = _check_cell(new_name)
    if text == "":
        raise GdocsError("column name is missing")
    current = headers[index] if index < len(headers) else ""
    if current == text:
        raise GdocsError("edit changed nothing")
    if any(header == text for header in headers):
        raise GdocsError("duplicate header names")
    letter = column_letter(index)
    assert_cell_budget([[text]])
    response = _values_call(
        creds,
        "update",
        spreadsheet_id,
        qualify_range(title, f"{letter}1"),
        option,
        {"values": [[text]]},
    )
    _require_cells(response)
    return {"id": spreadsheet_id, "updated": True}


def _grid_from_payload(creds, spreadsheet_id: str, title: str, kind: str, payload):
    if kind == "grid":
        return payload
    headers = header_list(_header_row(creds, spreadsheet_id, title))
    return objects_to_grid(headers, payload)


def _payload(values: str | None, json_path: str | None):
    if (values is None) == (json_path is None):
        raise GdocsError("pass one of --values or --json")
    if values is not None:
        return parse_json_payload(values)
    return parse_json_payload(read_text_input(json_path or "", MAX_VALUES_BYTES))


def _column_payload(values: str | None, json_path: str | None) -> list[list[str]]:
    kind, payload = _payload(values, json_path)
    if kind == "objects":
        raise GdocsError("column values must be one column")
    return _as_column(payload)


def _as_column(grid: list[list[str]]) -> list[list[str]]:
    if not grid:
        raise GdocsError("column values are empty")
    if len(grid) == 1:
        column = [[cell] for cell in grid[0]]
    elif all(len(row) == 1 for row in grid):
        column = [list(row) for row in grid]
    else:
        raise GdocsError("column values must be one column")
    if not column:
        raise GdocsError("column values are empty")
    return column


def _reject_same_column(existing: list[list[str]], index: int, column: list[list[str]]) -> None:
    data = existing[1:] if existing else []
    for offset, cell in enumerate(column):
        current = ""
        if offset < len(data) and index < len(data[offset]) and data[offset][index] is not None:
            current = str(data[offset][index])
        if current != cell[0]:
            return
    raise GdocsError("edit changed nothing")


def _one_cell(value: str | None, formula: str | None) -> str:
    if (value is None) == (formula is None):
        raise GdocsError("pass exactly one of --value or --formula")
    if formula is not None:
        if not isinstance(formula, str) or not formula.startswith("="):
            raise GdocsError("formula must start with =")
        return _check_cell(formula)
    return _check_cell(value)


def _row_mode(row, values, json_path, where, sets, insert, delete) -> str:
    modes = []
    if row is not None or values is not None or json_path is not None:
        modes.append("values")
    if where is not None or sets:
        modes.append("where")
    if insert is not None:
        modes.append("insert")
    if delete is not None:
        modes.append("delete")
    if len(modes) != 1:
        raise GdocsError("pass exactly one edit-row mode")
    return modes[0]


def _col_mode(source, values, json_path, insert, at, header, delete, rename) -> str:
    if at is not None and not insert:
        raise GdocsError("--at is only valid with --insert")
    if header is not None and not insert:
        raise GdocsError("--header is only valid with --insert")
    modes = []
    if source is not None:
        modes.append("from")
    if values is not None or json_path is not None:
        modes.append("values")
    if insert:
        modes.append("insert")
    if delete:
        modes.append("delete")
    if rename is not None:
        modes.append("rename")
    if len(modes) != 1:
        raise GdocsError("pass exactly one edit-col mode")
    return modes[0]


def _match_limit(all_matches: bool, limit: int | None) -> int:
    if limit is not None:
        content_limit(limit)
        capped = min(limit, _ALL_MATCH_CAP)
    else:
        capped = _ALL_MATCH_CAP
    if all_matches:
        return capped
    return 1 if limit is None else capped


def _check_head(head: int | None) -> None:
    if head is None:
        return
    if isinstance(head, bool) or not isinstance(head, int) or head < 1 or head > 1000:
        raise GdocsError("head must be between 1 and 1000")


def _check_displayed(value: int | None, message: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 1_000_000:
        raise GdocsError(message)


def _reject_range_text(range_a1: str | None) -> None:
    if not range_a1:
        return
    if any(ord(char) < 32 for char in range_a1) or len(range_a1) > 500:
        raise GdocsError("range is invalid")


def _column_tokens(cols: str) -> list[str]:
    if not isinstance(cols, str) or not cols.strip():
        raise GdocsError("columns are missing")
    tokens = [part.strip() for part in cols.split(",")]
    if not tokens or any(not token for token in tokens) or len(tokens) > 200:
        raise GdocsError("columns are missing")
    return tokens


def _stringify(grid) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in grid:
        if not isinstance(row, list):
            raise GdocsError("sheet values are invalid")
        rows.append(["" if cell is None else str(cell) for cell in row])
    return rows


def _require_cells(response: dict, nested: bool = False):
    if nested:
        updated = (response.get("updates") or {}).get("updatedCells")
    else:
        updated = response.get("updatedCells")
    if not updated:
        raise GdocsError("edit changed nothing")
    return updated


def _require_total(response: dict):
    total = response.get("totalUpdatedCells")
    if not total:
        raise GdocsError("edit changed nothing")
    return total


def create_sheet(name, columns, values=None, json_path=None, tab=None) -> dict:
    """Create a spreadsheet. Values are written RAW, so phones and ``=1+1`` stay literal.

    Formulas go through ``sheet update --formula``. ``--tab`` renames the first
    sheet after the values are written.
    """

    headers = parse_columns(columns)
    tab_title = check_tab_title(tab) if tab is not None else None
    title = check_title(name)
    if values is None and json_path is None:
        grid = [headers]
    else:
        kind, payload = _payload(values, json_path)
        grid = [headers] + _rows_under_header(headers, kind, payload)
    assert_cell_budget(grid)
    row = create_file("sheet", title)
    try:
        _fill_new_sheet(row["id"], grid, tab_title)
    except Exception as exc:
        abandon(row["id"], exc)
    return row


def import_records(path, *, name=None, tab=None) -> dict:
    """Create a spreadsheet from JSON records. Values are written RAW."""

    source = Path(path)
    if source.suffix.lower() != ".json":
        raise GdocsError("json import needs a .json file")
    tab_title = check_tab_title(tab) if tab is not None else None
    check_import_file(source)
    kind, payload = parse_json_payload(read_text_input(str(source), MAX_VALUES_BYTES))
    grid = grid_from_records(kind, payload)
    assert_cell_budget(grid)
    title = check_title(name or source.stem)
    row = create_file("sheet", title)
    try:
        _fill_new_sheet(row["id"], grid, tab_title)
    except Exception as exc:
        abandon(row["id"], exc)
    return row


def _rows_under_header(headers, kind, payload):
    if kind == "objects":
        return rows_for_header(headers, payload)
    width = len(headers)
    rows = []
    for row in payload:
        if len(row) > width:
            raise GdocsError("row is wider than the columns")
        rows.append(list(row) + [""] * (width - len(row)))
    return rows


def _fill_new_sheet(spreadsheet_id: str, grid, tab: str | None) -> None:
    from gdocs import services

    creds, _drive = open_drive(write=True)
    book = services.execute(
        _sheets(creds).spreadsheets().get(spreadsheetId=spreadsheet_id, fields=_META_FIELDS)
    )
    sheet = _pick_tab(book, None)
    response = _values_call(
        creds,
        "update",
        spreadsheet_id,
        qualify_range(sheet["title"], "A1"),
        "RAW",
        {"values": grid},
    )
    _require_cells(response)
    if tab is not None and tab != sheet["title"]:
        _batch(
            creds,
            spreadsheet_id,
            [
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": sheet["sheetId"], "title": tab},
                        "fields": "title",
                    }
                }
            ],
        )
