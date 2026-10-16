"""Slide deck JSON and a small YAML subset, plus slide text plans.

Threats: YAML is a restricted subset. Tags, anchors, and flow collections
are rejected. Unknown keys fail closed. Text is bounded before a request
is planned. Deck export is local text, not a Drive download. Does not
evaluate YAML or parse a view-shaped JSON as an editable deck.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from gdocs.errors import GdocsError
from gdocs.filesafe import check_import_file, read_text_input
from gdocs.grid import MAX_CELL, MAX_VALUES_BYTES

_OBJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_PLAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@+-]*$")
_KEY_LINE = re.compile(r"^([A-Za-z]+):(.*)$")
_DECK_KEYS = {"title", "slides"}
_SLIDE_KEYS = {"title", "body", "notes"}
_MAX_SLIDES = 300
_FIELDS = (
    ("title", ("TITLE", "CENTERED_TITLE"), "slide is missing a title placeholder"),
    ("body", ("BODY",), "slide is missing a body placeholder"),
    ("notes", ("BODY",), "slide is missing a notes placeholder"),
)
_FIELD_MESSAGES = {name: (kinds, message) for name, kinds, message in _FIELDS}


def check_object_id(object_id: str) -> str:
    if not isinstance(object_id, str) or not _OBJECT_ID.fullmatch(object_id):
        raise GdocsError("slide id is invalid")
    return object_id


def check_slide_ref(spec: str):
    if not isinstance(spec, str) or spec == "":
        raise GdocsError("slide was not found")
    if spec.isdigit():
        if len(spec) > 4 or int(spec) < 1:
            raise GdocsError("slide was not found")
        return ("index", int(spec))
    if not _OBJECT_ID.fullmatch(spec):
        raise GdocsError("slide id is invalid")
    return ("id", spec)


def plan_text_requests(object_id: str, shape, text: str) -> list[dict]:
    checked = check_object_id(object_id)
    current = shape if isinstance(shape, str) else _raw_shape_text(shape)
    user = bool(current.strip())
    if not user and text == "":
        return []
    requests: list[dict] = []
    if user:
        requests.append({"deleteText": {"objectId": checked, "textRange": {"type": "ALL"}}})
    if text != "":
        requests.append({"insertText": {"objectId": checked, "insertionIndex": 0, "text": text}})
    return requests


def plan_placeholder_writes(object_id, shape, text: str, *, missing: str, require_placeholders: bool) -> list[dict]:
    if object_id is None and (text != "" or require_placeholders):
        raise GdocsError(missing)
    if object_id is None:
        return []
    return plan_text_requests(object_id, shape, text)


def plan_field(page: dict, field: str, text, *, require_placeholders: bool) -> list[dict]:
    if text is None:
        return []
    if field not in _FIELD_MESSAGES:
        raise GdocsError("deck slide has an unknown key")
    if not isinstance(text, str):
        raise GdocsError("slide text must be text")
    if len(text) > MAX_CELL:
        raise GdocsError("text exceeds 50000 characters")
    kinds, missing = _FIELD_MESSAGES[field]
    if field == "notes":
        object_id, shape = _find_notes(page)
    else:
        object_id, shape = _find_placeholder(page, kinds)
    return plan_placeholder_writes(
        object_id,
        shape,
        text,
        missing=missing,
        require_placeholders=require_placeholders,
    )


def plan_slide_writes(page: dict, slide: dict, *, allow_empty: bool = False, require_placeholders: bool = True) -> list[dict]:
    if not isinstance(slide, dict):
        raise GdocsError("deck slide is invalid")
    for key in slide:
        if key not in _SLIDE_KEYS:
            raise GdocsError("deck slide has an unknown key")
    requests: list[dict] = []
    for field in ("title", "body", "notes"):
        if field not in slide:
            continue
        requests.extend(plan_field(page, field, slide[field], require_placeholders=require_placeholders))
    if not requests and not allow_empty:
        raise GdocsError("edit changed nothing")
    return requests


def plan_delete_slides(object_ids: list[str]) -> list[dict]:
    return [{"deleteObject": {"objectId": check_object_id(object_id)}} for object_id in object_ids]


def normalize_deck(deck) -> dict:
    if not isinstance(deck, dict):
        raise GdocsError("deck JSON is invalid")
    for key in deck:
        if key not in _DECK_KEYS:
            raise GdocsError("deck has an unknown key")
    if "title" in deck and not isinstance(deck["title"], str):
        raise GdocsError("deck title must be text")
    title = deck["title"] if "title" in deck else ""
    if len(title) > MAX_CELL:
        raise GdocsError("text exceeds 50000 characters")
    if "slides" not in deck or not isinstance(deck["slides"], list):
        raise GdocsError("deck needs slides")
    slides = deck["slides"]
    if len(slides) > _MAX_SLIDES:
        raise GdocsError("deck has too many slides")
    return {"title": title, "slides": [_normalize_slide(slide) for slide in slides]}


def load_deck(path: str) -> dict:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in {".json", ".yaml", ".yml"}:
        raise GdocsError("deck file must be json, yaml, or yml")
    check_import_file(source)
    text = read_text_input(str(source), MAX_VALUES_BYTES)
    if suffix == ".json":
        return _parse_json_deck(text)
    return parse_yaml_deck(text)


def parse_yaml_deck(text: str) -> dict:
    if not isinstance(text, str):
        raise GdocsError("yaml deck is invalid")
    if text.startswith("\ufeff"):
        text = text[1:]
    if len(text.encode("utf-8")) > MAX_VALUES_BYTES:
        raise GdocsError("input exceeds the size limit")
    if "\t" in text:
        raise GdocsError("yaml deck contains a tab")
    lines = text.splitlines()
    root: dict = {}
    seen: set[str] = set()
    index = 0
    while index < len(lines):
        raw = lines[index]
        if _blank(raw) or _comment(raw):
            index += 1
            continue
        if raw.strip() in {"---", "..."}:
            raise GdocsError("yaml deck is invalid")
        if _indent(raw) != 0:
            raise GdocsError("yaml deck is invalid")
        key, rest = _parse_key_rest(raw)
        if key in seen:
            raise GdocsError("yaml deck has a duplicate key")
        seen.add(key)
        if key not in _DECK_KEYS:
            raise GdocsError("deck has an unknown key")
        if key == "slides":
            if rest.strip() != "":
                raise GdocsError("yaml deck is invalid")
            slides, index = _read_slides(lines, index + 1)
            root["slides"] = slides
            continue
        value, index = _read_value(lines, index, rest, 0)
        root[key] = value
    return normalize_deck(root)


def emit_json(deck: dict) -> str:
    return json.dumps(deck, ensure_ascii=False, indent=2) + "\n"


def emit_yaml(deck: dict) -> str:
    lines = _emit_field("title", deck.get("title") or "", indent=0, dash=False)
    lines.append("slides:")
    for slide in deck.get("slides") or []:
        for offset, key in enumerate(("title", "body", "notes")):
            lines.extend(_emit_field(key, slide.get(key) or "", indent=4, dash=offset == 0))
    return "\n".join(lines) + "\n"


def slide_to_record(slide: dict) -> dict:
    title_id, title_shape = _find_placeholder(slide, ("TITLE", "CENTERED_TITLE"))
    body_id, body_shape = _find_placeholder(slide, ("BODY",))
    _notes_id, notes_shape = _find_notes(slide)
    del title_id, body_id
    return {
        "title": _one_newline(_raw_shape_text(title_shape)),
        "body": _one_newline(_raw_shape_text(body_shape)),
        "notes": _one_newline(_raw_shape_text(notes_shape)),
    }


def deck_from_presentation(presentation: dict) -> dict:
    title = presentation.get("title")
    if title is None:
        title = ""
    slides = [slide_to_record(slide) for slide in presentation.get("slides") or []]
    return normalize_deck({"title": title, "slides": slides})


def _normalize_slide(slide) -> dict:
    if not isinstance(slide, dict):
        raise GdocsError("deck slide is invalid")
    for key in slide:
        if key not in _SLIDE_KEYS:
            raise GdocsError("deck slide has an unknown key")
    record = {}
    for key in ("title", "body", "notes"):
        if key not in slide:
            record[key] = ""
            continue
        value = slide[key]
        if not isinstance(value, str):
            raise GdocsError("slide text must be text")
        if len(value) > MAX_CELL:
            raise GdocsError("text exceeds 50000 characters")
        record[key] = value
    return record


def _parse_json_deck(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise GdocsError("deck JSON is invalid") from None
    if not isinstance(data, dict):
        raise GdocsError("deck JSON is invalid")
    return normalize_deck(data)


def _read_slides(lines: list[str], index: int):
    slides = []
    while index < len(lines):
        raw = lines[index]
        if _blank(raw) or _comment(raw):
            index += 1
            continue
        if raw.strip() in {"---", "..."}:
            raise GdocsError("yaml deck is invalid")
        if _indent(raw) == 0:
            break
        if not raw.startswith("  - "):
            raise GdocsError("yaml deck is invalid")
        slide, index = _read_slide(lines, index, raw[4:])
        slides.append(slide)
    return slides, index


def _read_slide(lines: list[str], index: int, first: str):
    slide: dict = {}
    seen: set[str] = set()
    key, rest = _parse_key_rest(first)
    index = _store_slide_field(lines, index, slide, seen, key, rest)
    while index < len(lines):
        raw = lines[index]
        if _blank(raw):
            index += 1
            continue
        if raw.strip() in {"---", "..."}:
            raise GdocsError("yaml deck is invalid")
        if _comment(raw):
            if _indent(raw) < 4:
                break
            index += 1
            continue
        if _indent(raw) < 4:
            break
        if _indent(raw) != 4:
            raise GdocsError("yaml deck is invalid")
        key, rest = _parse_key_rest(raw[4:])
        index = _store_slide_field(lines, index, slide, seen, key, rest)
    return slide, index


def _store_slide_field(lines, index, slide, seen, key, rest) -> int:
    if key in seen:
        raise GdocsError("yaml deck has a duplicate key")
    seen.add(key)
    if key not in _SLIDE_KEYS:
        raise GdocsError("deck slide has an unknown key")
    value, index = _read_value(lines, index, rest, 4)
    slide[key] = value
    return index


def _read_value(lines: list[str], index: int, rest: str, key_indent: int):
    token = rest.strip()
    if token in {"|", "|-"}:
        return _read_block(lines, index + 1, key_indent)
    if token[:1] in {"|", ">"}:
        raise GdocsError("yaml deck is invalid")
    return _parse_scalar(rest), index + 1


def _read_block(lines: list[str], index: int, key_indent: int):
    content_indent = key_indent + 2
    chunks: list[str] = []
    started = False
    leading = 0
    trailing = 0
    while index < len(lines):
        raw = lines[index]
        if _blank(raw):
            if started:
                trailing += 1
            else:
                leading += 1
            index += 1
            continue
        if _comment(raw) and _indent(raw) <= key_indent:
            break
        if _comment(raw):
            index += 1
            continue
        if raw.strip() in {"---", "..."} and _indent(raw) <= key_indent:
            break
        if _indent(raw) <= key_indent:
            break
        if not started:
            started = True
            chunks.extend([""] * leading)
        else:
            chunks.extend([""] * trailing)
        trailing = 0
        chunks.append("" if len(raw) <= content_indent else raw[content_indent:])
        index += 1
    if not chunks:
        return "", index
    return "\n".join(chunks), index


def _parse_key_rest(text: str):
    match = _KEY_LINE.match(text)
    if not match:
        raise GdocsError("yaml deck is invalid")
    key, after = match.group(1), match.group(2)
    if key == "slides" and after.strip() == "":
        return key, ""
    if not after.startswith(" "):
        raise GdocsError("yaml deck is invalid")
    return key, after[1:]


def _parse_scalar(rest: str) -> str:
    text = rest.strip()
    if text == "":
        raise GdocsError("yaml deck is invalid")
    if text[0] == "'":
        raise GdocsError("yaml deck is invalid")
    if text[0] == '"':
        try:
            value, end = json.JSONDecoder().raw_decode(text)
        except json.JSONDecodeError:
            raise GdocsError("yaml deck is invalid") from None
        if not isinstance(value, str) or text[end:].strip() != "":
            raise GdocsError("yaml deck is invalid")
        return value
    if "#" in text:
        raise GdocsError("yaml comment must be a full line")
    if any(char in text for char in "!&*{}[]"):
        raise GdocsError("yaml deck is invalid")
    if ":" in text:
        raise GdocsError("yaml deck is invalid")
    if not _PLAIN.fullmatch(text):
        raise GdocsError("yaml deck is invalid")
    return text


def _emit_field(key: str, value: str, *, indent: int, dash: bool) -> list[str]:
    if "\n" in value:
        parts = value.split("\n")
        if value.endswith("\n"):
            parts = parts[:-1]
        if any(parts):
            lines = [_head(key, "|", indent, dash)]
            pad = " " * (indent + 2)
            for part in parts:
                lines.append(pad + part if part else "")
            return lines
        value = ""
    if value == "":
        rendered = '""'
    elif _PLAIN.fullmatch(value):
        rendered = value
    else:
        rendered = json.dumps(value, ensure_ascii=False)
    return [_head(key, rendered, indent, dash)]


def _head(key: str, rendered: str, indent: int, dash: bool) -> str:
    if dash:
        return f"  - {key}: {rendered}"
    return f"{' ' * indent}{key}: {rendered}"


def _one_newline(text: str) -> str:
    if text.endswith("\n"):
        text = text[:-1]
    if len(text) > MAX_CELL:
        raise GdocsError("text exceeds 50000 characters")
    return text


def _raw_shape_text(shape) -> str:
    if isinstance(shape, str):
        return shape
    if not isinstance(shape, dict):
        return ""
    if "text" not in shape and "shape" in shape:
        shape = shape.get("shape") or {}
    parts: list[str] = []
    for element in (shape.get("text") or {}).get("textElements") or []:
        if not isinstance(element, dict):
            continue
        content = (element.get("textRun") or {}).get("content")
        if isinstance(content, str):
            parts.append(content)
    return "".join(parts)


def _find_placeholder(page: dict, kinds: tuple[str, ...]):
    elements = page.get("pageElements") or []
    for kind in kinds:
        for element in elements:
            if _placeholder_type(element) == kind:
                return element.get("objectId"), element.get("shape") or {}
    return None, None


def _find_notes(slide: dict):
    notes = (slide.get("slideProperties") or {}).get("notesPage") or {}
    for element in notes.get("pageElements") or []:
        if _placeholder_type(element) == "BODY":
            return element.get("objectId"), element.get("shape") or {}
    return None, None


def _placeholder_type(element: dict) -> str | None:
    if not isinstance(element, dict):
        return None
    shape = element.get("shape") or {}
    placeholder = shape.get("placeholder") if isinstance(shape, dict) else None
    if not placeholder:
        placeholder = element.get("placeholder") or {}
    if not isinstance(placeholder, dict):
        return None
    return placeholder.get("type")


def _indent(raw: str) -> int:
    return len(raw) - len(raw.lstrip(" "))


def _blank(raw: str) -> bool:
    return raw.strip() == ""


def _comment(raw: str) -> bool:
    return raw.lstrip(" ").startswith("#")
