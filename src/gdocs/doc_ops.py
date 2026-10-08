"""Docs read and text edits.

Threats: replace and append text are bounded before a request is sent.
Append uses the API end index, never Python's character length and never
index 0. Does not interpret Markdown on import; that conversion is Drive's.
"""

from __future__ import annotations

from gdocs.drive_ops import open_drive, resolve
from gdocs.errors import GdocsError
from gdocs.extract import (
    append_location,
    document_text,
    replace_request,
    require_text_changes,
    simplified_doc,
)

_FORMATS = {"md", "text", "json"}


def view(target: str, *, fmt: str = "json", raw: bool = False):
    document = _load(target, write=False)
    if raw:
        return document
    if fmt not in _FORMATS:
        raise GdocsError("format must be md, text, or json")
    if fmt == "md":
        return document_text(document, markdown=True)
    if fmt == "text":
        return document_text(document, markdown=False)
    return simplified_doc(document)


def replace_text(target: str, old: str, new: str) -> dict:
    request = replace_request(old, new)
    creds, drive = open_drive(write=True)
    meta = resolve(drive, "doc", target)
    response = _batch(creds, meta["id"], [request])
    changed = require_text_changes(response)
    return {"id": meta["id"], "occurrencesChanged": changed}


def append_text(target: str, text: str) -> dict:
    if not isinstance(text, str) or text == "":
        raise GdocsError("refusing to append empty text")
    if len(text) > 50000:
        raise GdocsError("text exceeds 50000 characters")
    creds, drive = open_drive(write=True)
    meta = resolve(drive, "doc", target)
    document = _documents(creds).documents().get(documentId=meta["id"], includeTabsContent=True)
    from gdocs import services

    loaded = services.execute(document)
    location = append_location(loaded)
    _batch(creds, meta["id"], [{"insertText": {"location": location, "text": text}}])
    return {"id": meta["id"], "appended": len(text)}


def _load(target: str, *, write: bool) -> dict:
    from gdocs import services

    creds, drive = open_drive(write=write)
    meta = resolve(drive, "doc", target)
    request = _documents(creds).documents().get(documentId=meta["id"], includeTabsContent=True)
    return services.execute(request)


def _batch(creds, document_id: str, requests: list[dict]) -> dict:
    from gdocs import services

    return services.execute(
        _documents(creds).documents().batchUpdate(documentId=document_id, body={"requests": requests})
    )


def _documents(creds):
    from gdocs import services

    return services.build("docs", "v1", creds)
