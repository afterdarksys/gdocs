"""Local sheet filter language and edit planning.

Threats: the filter language must not execute code. There is no eval.
``OR``, ``import``, and unknown operators are rejected. Numeric comparisons
fail closed when a value is not a plain number. A delete request is not
built unless ``yes`` is true. Does not protect against a hostile spreadsheet
formula the user later opens in Sheets.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass

from gdocs.errors import GdocsError

MAX_WHERE = 2000
MAX_CELL = 50000
MAX_CELLS = 50000
MAX_VALUES_BYTES = 8_000_000
MAX_ROWS = 20000
_CELL = re.compile(r"^([A-Za-z]{1,3})([1-9][0-9]*)$")
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_OPS = (">=", "<=", "!=", "=", ">", "<")
_NUMERIC_OPS = {">", ">=", "<", "<="}
_REJECTED_WORDS = {"eval", "exec", "import", "compile", "__import__", "open", "getattr"}


@dataclass(frozen=True)
class Clause:
    field: str
    op: str
    value: str
    numeric: bool


def column_index(letters: str) -> int:
    if not re.fullmatch(r"[A-Za-z]{1,3}", letters or ""):
        raise GdocsError("column letter is invalid")
    number = 0
    for char in letters.upper():
        number = number * 26 + (ord(char) - 64)
    index = number - 1
    if index < 0 or index > 16383:
        raise GdocsError("column letter is invalid")
    return index


def column_letter(index: int) -> str:
    if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index > 16383:
        raise GdocsError("column index is invalid")
    number = index + 1
    chars: list[str] = []
    while number:
        number, rem = divmod(number - 1, 26)
        chars.append(chr(65 + rem))
    return "".join(reversed(chars))


def parse_cell(cell: str) -> tuple[int, int]:
    match = _CELL.fullmatch((cell or "").strip())
    if not match:
        raise GdocsError("cell must look like F2")
    column = column_index(match.group(1))
    row = int(match.group(2))
    if row > 1_000_000:
        raise GdocsError("row number is too large")
    return column, row


def quote_sheet_name(name: str) -> str:
    if not isinstance(name, str) or name == "":
        raise GdocsError("sheet name is missing")
    if any(ord(char) < 32 for char in name):
        raise GdocsError("sheet name is invalid")
    if re.fullmatch(r"[A-Za-z0-9_]+", name):
        return name
    return "'" + name.replace("'", "''") + "'"


def qualify_range(sheet: str | None, range_a1: str | None) -> str:
    if range_a1:
        if any(ord(char) < 32 for char in range_a1) or len(range_a1) > 500:
            raise GdocsError("range is invalid")
        if "!" in range_a1:
            return range_a1
        if not sheet:
            raise GdocsError("a range without a sheet needs --tab or a Sheet!A1 range")
        return f"{quote_sheet_name(sheet)}!{range_a1}"
    if not sheet:
        raise GdocsError("missing sheet tab")
    return quote_sheet_name(sheet)


def parse_where(text: str) -> list[Clause]:
    if not isinstance(text, str) or not text.strip():
        raise GdocsError("where clause is empty")
    if len(text) > MAX_WHERE:
        raise GdocsError("where clause is too long")
    tokens = _tokenize(text)
    clauses: list[Clause] = []
    index = 0
    expect_and = False
    while index < len(tokens):
        if expect_and:
            if tokens[index][0] != "and":
                raise GdocsError("where clauses must be joined with AND")
            index += 1
        if index + 2 >= len(tokens):
            raise GdocsError("where clause is incomplete")
        field, op, value = tokens[index], tokens[index + 1], tokens[index + 2]
        if field[0] != "word" or op[0] != "op" or value[0] not in {"word", "string", "number"}:
            raise GdocsError("where clause must be a field, an operator, and a value")
        if field[1] in _REJECTED_WORDS:
            raise GdocsError("where clause rejected")
        if op[1] in _NUMERIC_OPS and value[0] != "number":
            raise GdocsError("numeric compare needs a number")
        if op[1] == "contains" and value[1] == "":
            raise GdocsError("contains value is empty")
        numeric = value[0] == "number" and op[1] != "contains"
        clauses.append(Clause(field[1], op[1], value[1], numeric))
        index += 3
        expect_and = True
        if len(clauses) > 20:
            raise GdocsError("where clause has too many conditions")
    return clauses


def header_list(grid: list[list[str]]) -> list[str]:
    if not grid:
        raise GdocsError("sheet has no header row")
    headers = ["" if cell is None else str(cell).strip() for cell in grid[0]]
    names = [header for header in headers if header]
    if len(names) != len(set(names)):
        raise GdocsError("duplicate header names")
    return headers


def resolve_column(token: str, headers: list[str]) -> int:
    exact = [index for index, header in enumerate(headers) if header == token]
    if len(exact) > 1:
        raise GdocsError(f"column {token} is ambiguous")
    if len(exact) == 1:
        return exact[0]
    if re.fullmatch(r"[A-Za-z]{1,3}", token or ""):
        return column_index(token)
    raise GdocsError(f"unknown column {token}")


def filter_rows(grid: list[list[str]], clauses: list[Clause]) -> list[dict[str, str]]:
    if not grid:
        return []
    headers = header_list(grid)
    matched: list[dict[str, str]] = []
    for row in grid[1:]:
        padded = _pad(row, max(len(headers), _width(clauses, headers)))
        if all(_matches(padded, headers, clause) for clause in clauses):
            matched.append(_record(headers, padded))
    return matched


def matching_sheet_rows(grid: list[list[str]], clauses: list[Clause]) -> list[int]:
    """Return 1-based sheet row numbers. The header is row 1 and is never matched."""

    headers = header_list(grid)
    found: list[int] = []
    width = max(len(headers), _width(clauses, headers))
    for offset, row in enumerate(grid[1:], start=2):
        padded = _pad(row, width)
        if all(_matches(padded, headers, clause) for clause in clauses):
            found.append(offset)
    return found


def require_match_count(rows: list[int], all_matches: bool, limit: int) -> list[int]:
    if not rows:
        raise GdocsError("no matching rows")
    if len(rows) > 1 and not all_matches:
        raise GdocsError(f"{len(rows)} matching rows; pass --all")
    if len(rows) > limit:
        raise GdocsError("matching rows exceed --limit")
    return rows


def parse_sets(items: list[str]) -> dict[str, str]:
    if not items:
        raise GdocsError("missing --set column=value")
    parsed: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise GdocsError("set must be column=value")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise GdocsError("set is missing a column")
        if key in parsed:
            raise GdocsError(f"duplicate set for {key}")
        parsed[key] = _check_cell(value)
    return parsed


def apply_set(row: list[str], headers: list[str], sets: dict[str, str]) -> list[str]:
    width = max(len(headers), len(row), max(resolve_column(key, headers) for key in sets) + 1)
    updated = _pad(row, width)
    changed = False
    for key, value in sets.items():
        index = resolve_column(key, headers)
        if updated[index] != value:
            updated[index] = value
            changed = True
    if not changed:
        raise GdocsError("edit changed nothing")
    return updated


def plan_copy_column(grid: list[list[str]], dest_name: str, source_name: str) -> list[list[str]]:
    headers = header_list(grid)
    dest = resolve_column(dest_name, headers)
    source = resolve_column(source_name, headers)
    if dest == source:
        raise GdocsError("edit changed nothing")
    values: list[list[str]] = []
    changed = False
    for row in grid[1:]:
        source_value = row[source] if source < len(row) else ""
        dest_value = row[dest] if dest < len(row) else ""
        source_value = "" if source_value is None else str(source_value)
        dest_value = "" if dest_value is None else str(dest_value)
        if source_value != dest_value:
            changed = True
        values.append([source_value])
    if not values:
        raise GdocsError("column has no data rows")
    if not changed:
        raise GdocsError("edit changed nothing")
    return values


def plan_insert(sheet_id: int, dimension: str, displayed_index: int) -> dict:
    start = _displayed_start(displayed_index)
    return {
        "insertDimension": {
            "range": {
                "sheetId": sheet_id,
                "dimension": dimension,
                "startIndex": start,
                "endIndex": start + 1,
            },
            "inheritFromBefore": start > 0,
        }
    }


def plan_delete(sheet_id: int, dimension: str, displayed_index: int, yes: bool) -> dict:
    if not yes:
        raise GdocsError("refusing to delete without --yes")
    start = _displayed_start(displayed_index)
    return {
        "deleteDimension": {
            "range": {
                "sheetId": sheet_id,
                "dimension": dimension,
                "startIndex": start,
                "endIndex": start + 1,
            }
        }
    }


def plan_basic_filter(sheet_id: int, headers: list[str], clauses: list[Clause]) -> dict:
    criteria: dict[str, dict] = {}
    indexes: list[int] = []
    for clause in clauses:
        index = resolve_column(clause.field, headers)
        if index in indexes:
            raise GdocsError("basic filter cannot apply two clauses to one column")
        indexes.append(index)
        criteria[str(index)] = {"condition": _condition(clause)}
    end_column = max(len(headers), max(indexes) + 1)
    return {
        "setBasicFilter": {
            "filter": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "startColumnIndex": 0,
                    "endColumnIndex": end_column,
                },
                "criteria": criteria,
            }
        }
    }


def value_input_option(*, raw: bool, formula: bool) -> str:
    if raw and formula:
        raise GdocsError("pass only one of --raw and --formula")
    if raw:
        return "RAW"
    return "USER_ENTERED"


def parse_value_grid(text: str) -> list[list[str]]:
    kind, payload = parse_json_payload(text)
    if kind == "objects":
        raise GdocsError("object rows need a header; use --json on append")
    return payload


def parse_json_payload(text: str):
    if not isinstance(text, str):
        raise GdocsError("values are missing")
    if len(text.encode("utf-8")) > MAX_VALUES_BYTES:
        raise GdocsError("values exceed 8000000 bytes")
    stripped = text.strip()
    if not stripped:
        raise GdocsError("values are empty")
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            raise GdocsError("values JSON is invalid") from None
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list) or not data:
            raise GdocsError("values JSON must be a non-empty array")
        if len(data) > MAX_ROWS:
            raise GdocsError("too many rows")
        if all(isinstance(item, dict) for item in data):
            return "objects", data
        if all(not isinstance(item, list) for item in data):
            return "grid", [_check_row(data)]
        if all(isinstance(item, list) for item in data):
            return "grid", [_check_row(item) for item in data]
        raise GdocsError("values JSON must be an array of rows")
    row = next(csv.reader([stripped]))
    return "grid", [_check_row(row)]


def objects_to_grid(headers: list[str], objects: list[dict]) -> list[list[str]]:
    index = {header: position for position, header in enumerate(headers) if header}
    if not index:
        raise GdocsError("sheet has no header row")
    if not objects:
        raise GdocsError("json rows are empty")
    if len(objects) > MAX_ROWS:
        raise GdocsError("too many rows")
    width = max(index.values()) + 1
    rows: list[list[str]] = []
    for obj in objects:
        if not isinstance(obj, dict):
            raise GdocsError("json rows must be objects")
        unknown = [key for key in obj if key not in index]
        if unknown:
            raise GdocsError("json row has unknown columns")
        row = [""] * width
        for key, value in obj.items():
            row[index[key]] = _check_cell(value)
        rows.append(row)
    return rows


def records_from_grid(grid: list[list[str]]) -> list[dict[str, str]]:
    if not grid:
        return []
    headers = header_list(grid)
    return [_record(headers, _pad(row, len(headers))) for row in grid[1:]]


def parse_csv_text(text: str) -> list[list[str]]:
    if len(text.encode("utf-8")) > MAX_VALUES_BYTES:
        raise GdocsError("csv exceeds 8000000 bytes")
    rows: list[list[str]] = []
    for record in csv.reader(io.StringIO(text)):
        if len(rows) >= MAX_ROWS:
            raise GdocsError("csv exceeds 20000 rows")
        rows.append(_check_row(record))
    if not rows:
        raise GdocsError("csv is empty")
    return rows


def assert_cell_budget(grid: list) -> None:
    total = 0
    for row in grid:
        total += len(row)
        if total > MAX_CELLS:
            raise GdocsError("values exceed 50000 cells")


def content_limit(value: int | None) -> int:
    if value is None:
        return MAX_ROWS
    if value < 1 or value > MAX_ROWS:
        raise GdocsError("limit must be between 1 and 20000")
    return value


def list_limit(value: int | None) -> int:
    if value is None:
        return 50
    if value < 1 or value > 1000:
        raise GdocsError("limit must be between 1 and 1000")
    return value


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char in "\"'":
            quote = char
            index += 1
            buffer: list[str] = []
            while index < length and text[index] != quote:
                if text[index] == "\\":
                    index += 1
                    if index >= length:
                        raise GdocsError("unterminated escape in where value")
                buffer.append(text[index])
                index += 1
            if index >= length or text[index] != quote:
                raise GdocsError("unterminated string in where clause")
            index += 1
            tokens.append(("string", "".join(buffer)))
            continue
        matched = False
        for op in _OPS:
            if text.startswith(op, index):
                tokens.append(("op", op))
                index += len(op)
                matched = True
                break
        if matched:
            continue
        word = re.match(r"[A-Za-z_][A-Za-z0-9_]*", text[index:])
        if word:
            lexeme = word.group(0)
            index += len(lexeme)
            if lexeme == "OR":
                raise GdocsError("OR is not supported in where clauses")
            if lexeme == "AND":
                tokens.append(("and", lexeme))
            elif lexeme == "contains":
                tokens.append(("op", "contains"))
            else:
                tokens.append(("word", lexeme))
            continue
        number = re.match(r"-?\d+(?:\.\d+)?", text[index:])
        if number:
            tokens.append(("number", number.group(0)))
            index += len(number.group(0))
            continue
        raise GdocsError("where clause has an invalid token")
    return tokens


def _matches(row: list[str], headers: list[str], clause: Clause) -> bool:
    cell = _cell(row, headers, clause)
    if clause.op == "=":
        return cell == clause.value
    if clause.op == "!=":
        if clause.numeric:
            return _number(cell) != _number(clause.value)
        return cell != clause.value
    if clause.op == "contains":
        return clause.value.casefold() in cell.casefold()
    left = _number(cell)
    right = _number(clause.value)
    if clause.op == ">":
        return left > right
    if clause.op == ">=":
        return left >= right
    if clause.op == "<":
        return left < right
    if clause.op == "<=":
        return left <= right
    raise GdocsError("unknown operator")


def _cell(row: list[str], headers: list[str], clause: Clause) -> str:
    index = resolve_column(clause.field, headers)
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index])


def _number(value: str) -> float:
    if not _NUMBER.fullmatch(value.strip()):
        raise GdocsError("numeric compare needs a number")
    return float(value)


def _condition(clause: Clause) -> dict:
    if clause.op == "contains":
        kind = "TEXT_CONTAINS"
    elif clause.op == "=" and clause.numeric:
        kind = "NUMBER_EQ"
    elif clause.op == "!=" and clause.numeric:
        kind = "NUMBER_NOT_EQ"
    elif clause.op == "=":
        kind = "TEXT_EQ"
    elif clause.op == "!=":
        raise GdocsError("basic filter cannot express a text inequality")
    elif clause.op == ">":
        kind = "NUMBER_GREATER"
    elif clause.op == ">=":
        kind = "NUMBER_GREATER_THAN_EQ"
    elif clause.op == "<":
        kind = "NUMBER_LESS"
    elif clause.op == "<=":
        kind = "NUMBER_LESS_THAN_EQ"
    else:
        raise GdocsError("operator cannot be applied as a basic filter")
    return {"type": kind, "values": [{"userEnteredValue": clause.value}]}


def _record(headers: list[str], row: list[str]) -> dict[str, str]:
    record: dict[str, str] = {}
    for index, header in enumerate(headers):
        if header:
            record[header] = row[index] if index < len(row) else ""
    return record


def _pad(row: list[str], width: int) -> list[str]:
    values = ["" if cell is None else str(cell) for cell in row]
    if len(values) < width:
        values.extend([""] * (width - len(values)))
    return values


def _width(clauses: list[Clause], headers: list[str]) -> int:
    if not clauses:
        return len(headers)
    return max(resolve_column(clause.field, headers) for clause in clauses) + 1


def _displayed_start(displayed_index: int) -> int:
    if not isinstance(displayed_index, int) or isinstance(displayed_index, bool) or displayed_index < 1:
        raise GdocsError("index must be 1 or greater")
    if displayed_index > 1_000_000:
        raise GdocsError("index is too large")
    return displayed_index - 1


def _check_row(row: list) -> list[str]:
    if len(row) > 200:
        raise GdocsError("a row has too many cells")
    return [_check_cell(cell) for cell in row]


def _check_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, float):
        text = str(int(value)) if value.is_integer() else format(value, ".15g")
    else:
        text = str(value)
    if len(text) > MAX_CELL:
        raise GdocsError("cell exceeds 50000 characters")
    return text
