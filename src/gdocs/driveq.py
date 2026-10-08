"""Drive query text, tags, and share-body planning.

Threats: quote injection into the Drive ``q`` parameter, tag values that
overflow the 124-byte appProperties budget, and a public share built without
--yes. Does not protect against a file an attacker already stored in Drive.
"""

from __future__ import annotations

import re

from gdocs.errors import GdocsError

KIND_MIME = {
    "doc": "application/vnd.google-apps.document",
    "sheet": "application/vnd.google-apps.spreadsheet",
    "present": "application/vnd.google-apps.presentation",
}
TAG_KEY = "gdocs_tags"
# Drive allows 124 UTF-8 bytes for key + value. The key is 11 bytes.
MAX_TAG_VALUE = 113
MAX_QUERY_TEXT = 500
_TAG = re.compile(r"^[A-Za-z0-9_.:@+-]{1,64}$")
_ID = re.compile(r"^[A-Za-z0-9_-]{20,}$")
_URL_ID = re.compile(r"/(?:document|spreadsheets|presentation)/d/([A-Za-z0-9_-]{20,})")
_OPEN_ID = re.compile(r"[?&]id=([A-Za-z0-9_-]{20,})")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMAIN = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

EXPORT_MIME = {
    "doc": {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain",
        "html": "text/html",
        "md": "text/markdown",
    },
    "sheet": {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
        "pdf": "application/pdf",
        "ods": "application/vnd.oasis.opendocument.spreadsheet",
    },
    "present": {
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pdf": "application/pdf",
        "txt": "text/plain",
    },
}
IMPORT_SOURCE = {
    "md": "text/plain",
    "txt": "text/plain",
    "html": "text/html",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
IMPORT_KIND = {
    "doc": {"md", "txt", "html", "docx"},
    "sheet": {"xlsx", "csv"},
    "present": {"pptx"},
}
LIST_FIELDS = "nextPageToken, files(id, name, mimeType, modifiedTime, starred, webViewLink, appProperties)"
FILE_FIELDS = "id, name, mimeType, modifiedTime, starred, webViewLink, appProperties"
FILE_COLUMNS = ["id", "name", "modifiedTime", "starred", "tags", "webViewLink"]


def escape_drive_string(value: str) -> str:
    """Escape a string for a Drive query literal. Backslash first, then quote."""

    if any(ord(ch) < 32 for ch in value):
        raise GdocsError("query text contains control characters")
    return value.replace("\\", "\\\\").replace("'", "\\'")


def check_tag(tag: str) -> str:
    if not isinstance(tag, str) or not _TAG.fullmatch(tag):
        raise GdocsError("tag must be 1-64 characters from letters, numbers, and _.:@+-")
    return tag


def parse_tags(value: str | None) -> list[str]:
    if value is None or value == "":
        return []
    if not isinstance(value, str):
        raise GdocsError("stored tags are invalid")
    parts = [part for part in value.split(",") if part]
    for part in parts:
        check_tag(part)
    return parts


def dump_tags(tags: list[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for tag in tags:
        check_tag(tag)
        if tag not in seen:
            seen.add(tag)
            ordered.append(tag)
    if not ordered:
        return ""
    value = "," + ",".join(ordered) + ","
    size = len(value.encode("utf-8"))
    if size > MAX_TAG_VALUE:
        raise GdocsError(f"tags exceed the Drive property budget ({size} > {MAX_TAG_VALUE} bytes)")
    return value


def merge_tag_map(props: dict | None, *, add: tuple[str, ...] = (), remove: tuple[str, ...] = ()) -> tuple[dict, bool]:
    """Read-modify-write ``appProperties``. A null ``gdocs_tags`` clears that key."""

    if props is None:
        props = {}
    if not isinstance(props, dict):
        raise GdocsError("appProperties is invalid")
    cleaned: dict[str, str | None] = {}
    for key, value in props.items():
        if not isinstance(key, str) or not key or len(key.encode("utf-8")) > 44:
            raise GdocsError("appProperties key is invalid")
        if value is None:
            continue
        if not isinstance(value, str):
            raise GdocsError("appProperties value is invalid")
        cleaned[key] = value
    current = parse_tags(cleaned.get(TAG_KEY) or "")
    updated = list(current)
    changed = False
    for tag in remove:
        check_tag(tag)
        if tag not in updated:
            raise GdocsError(f"tag {tag} is not set")
        updated = [item for item in updated if item != tag]
        changed = True
    for tag in add:
        check_tag(tag)
        if tag in updated:
            raise GdocsError(f"tag {tag} is already set")
        updated.append(tag)
        changed = True
    value = dump_tags(updated)
    if value:
        if cleaned.get(TAG_KEY) != value:
            changed = True
        cleaned[TAG_KEY] = value
    elif TAG_KEY in cleaned:
        cleaned[TAG_KEY] = None
        changed = True
    live = [key for key, item in cleaned.items() if item is not None]
    if len(live) > 30:
        raise GdocsError("file already has 30 private properties")
    return cleaned, changed


def build_list_query(
    *,
    kind: str,
    name_contains: str | None = None,
    name_equals: str | None = None,
    full_text: str | None = None,
    tag: str | None = None,
    starred: bool = False,
) -> str:
    mime = KIND_MIME[kind]
    parts = ["trashed = false", f"mimeType = '{mime}'"]
    if name_contains is not None and name_equals is not None:
        raise GdocsError("use only one name match")
    if name_contains is not None:
        parts.append(f"name contains '{escape_drive_string(_query_text(name_contains))}'")
    if name_equals is not None:
        parts.append(f"name = '{escape_drive_string(_query_text(name_equals))}'")
    if full_text is not None:
        parts.append(f"fullText contains '{escape_drive_string(_query_text(full_text))}'")
    if tag is not None:
        check_tag(tag)
        wrapped = "," + tag + ","
        parts.append(
            "appProperties has { key='gdocs_tags' and value contains '"
            + escape_drive_string(wrapped)
            + "' }"
        )
    if starred:
        parts.append("starred = true")
    query = " and ".join(parts)
    if len(query) > 2000:
        raise GdocsError("query is too long")
    return query


def extract_id(target: str) -> str | None:
    if not isinstance(target, str) or not target.strip():
        raise GdocsError("missing file target")
    if len(target) > 2000:
        raise GdocsError("file target is too long")
    found = _URL_ID.search(target)
    if found:
        return found.group(1)
    if target.startswith("http://") or target.startswith("https://"):
        found = _OPEN_ID.search(target)
        if found:
            return found.group(1)
        raise GdocsError("URL does not contain a file id")
    if _ID.fullmatch(target):
        return target
    return None


def file_row(meta: dict) -> dict:
    raw = (meta.get("appProperties") or {}).get(TAG_KEY)
    try:
        tags = parse_tags(raw)
    except GdocsError:
        tags = []
    return {
        "id": meta.get("id"),
        "name": meta.get("name"),
        "modifiedTime": meta.get("modifiedTime"),
        "starred": bool(meta.get("starred")),
        "tags": ",".join(tags),
        "webViewLink": meta.get("webViewLink"),
    }


def plan_share(who: str, role: str, yes: bool) -> dict:
    if role not in {"reader", "commenter", "writer"}:
        raise GdocsError("role must be reader, commenter, or writer")
    if who == "anyone":
        if not yes:
            raise GdocsError("refusing to share with anyone without --yes")
        return {"type": "anyone", "role": role, "allowFileDiscovery": False}
    if ":" not in who:
        raise GdocsError("who must be user:email, group:email, domain:name, or anyone")
    kind, value = who.split(":", 1)
    if kind in {"user", "group"}:
        if not _EMAIL.fullmatch(value) or len(value) > 254:
            raise GdocsError("email address is invalid")
        return {"type": kind, "role": role, "emailAddress": value}
    if kind == "domain":
        if not _DOMAIN.fullmatch(value) or len(value) > 253:
            raise GdocsError("domain is invalid")
        return {"type": "domain", "role": role, "domain": value}
    raise GdocsError("who must be user:, group:, domain:, or anyone")


def export_mime(kind: str, fmt: str) -> str:
    table = EXPORT_MIME.get(kind) or {}
    mime = table.get(fmt)
    if not mime:
        choices = ", ".join(sorted(table))
        raise GdocsError(f"export format must be one of: {choices}")
    return mime


def import_types(kind: str, suffix: str) -> tuple[str, str]:
    suffix = suffix.lower().lstrip(".")
    if suffix not in IMPORT_KIND.get(kind, set()):
        raise GdocsError("this file type cannot be imported here")
    return IMPORT_SOURCE[suffix], KIND_MIME[kind]


def _query_text(value: str) -> str:
    if not isinstance(value, str) or value == "":
        raise GdocsError("query text is empty")
    if len(value) > MAX_QUERY_TEXT:
        raise GdocsError("query text is too long")
    return value
