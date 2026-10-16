"""Slides read, replace-all, and title-and-body edits.

Threats: text is bounded before a request is sent. A new slide is deleted
if the following text write fails. Deck import and export stay on the local
schema. Does not export thumbnails.
"""

from __future__ import annotations

from pathlib import Path

from gdocs.deck import (
    check_object_id,
    check_slide_ref,
    deck_from_presentation,
    emit_json,
    emit_yaml,
    load_deck,
    normalize_deck,
    plan_delete_slides,
    plan_slide_writes,
)
from gdocs.drive_ops import abandon, check_title, create_file, open_drive, resolve
from gdocs.errors import GdocsError
from gdocs.extract import presentation_view, replace_request, require_text_changes
from gdocs.filesafe import atomic_write, prepare_output

_CHUNK = 100
_DECK_FORMATS = {"json", "yaml", "yml"}


def view(target: str, *, raw: bool = False):
    presentation = _load(target, write=False)
    if raw:
        return presentation
    return presentation_view(presentation)


def replace_text(target: str, old: str, new: str) -> dict:
    request = replace_request(old, new)
    creds, drive = open_drive(write=True)
    meta = resolve(drive, "present", target)
    from gdocs import services

    response = services.execute(
        _presentations(creds).presentations().batchUpdate(
            presentationId=meta["id"],
            body={"requests": [request]},
        )
    )
    changed = require_text_changes(response)
    return {"id": meta["id"], "occurrencesChanged": changed}


def add_slide(target: str, title: str | None, body: str | None, notes: str | None = None) -> dict:
    _check_slide_text(title, body, notes)
    creds, drive = open_drive(write=True)
    meta = resolve(drive, "present", target)
    from gdocs import services

    service = _presentations(creds)
    created = services.execute(
        service.presentations().batchUpdate(
            presentationId=meta["id"],
            body={
                "requests": [
                    {"createSlide": {"slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"}}}
                ]
            },
        )
    )
    object_id = None
    try:
        raw_id = _created_slide_id(created)
        object_id = check_object_id(raw_id)
        presentation = services.execute(service.presentations().get(presentationId=meta["id"]))
        page = _find_page(presentation, object_id)
        slide: dict[str, str] = {}
        if title:
            slide["title"] = title
        if body:
            slide["body"] = body
        if notes:
            slide["notes"] = notes
        requests = plan_slide_writes(page, slide)
        services.execute(
            service.presentations().batchUpdate(
                presentationId=meta["id"],
                body={"requests": requests},
            )
        )
    except Exception:
        if object_id:
            try:
                services.execute(
                    service.presentations().batchUpdate(
                        presentationId=meta["id"],
                        body={"requests": [{"deleteObject": {"objectId": object_id}}]},
                    )
                )
            except Exception:
                pass
        raise
    return {"id": meta["id"], "slide": object_id}


def create(name: str, deck: dict | None = None) -> dict:
    """Blank presentation. Deck text is written after the file exists."""

    title = check_title(name)
    loaded = normalize_deck(deck) if deck is not None else None
    row = create_file("present", title)
    if loaded is None or not loaded["slides"]:
        return row
    try:
        _fill_deck(row["id"], loaded)
    except Exception as exc:
        abandon(row["id"], exc)
    return row


def import_deck(path: str, name: str | None = None) -> dict:
    """Create a presentation from a JSON or YAML deck."""

    deck = load_deck(path)
    chosen = name if name else (deck["title"] or Path(path).stem)
    return create(chosen, deck=deck)


def export_deck(target: str, fmt: str, dest: str, force: bool) -> dict:
    """Write a local JSON or YAML deck. Layouts other than title and body are lossy."""

    if fmt not in _DECK_FORMATS:
        raise GdocsError("export format must be one of: json, yaml, yml")
    path = Path(dest)
    prepare_output(path, force)
    from gdocs import services

    creds, drive = open_drive(write=False)
    meta = resolve(drive, "present", target)
    presentation = services.execute(
        _presentations(creds).presentations().get(presentationId=meta["id"])
    )
    deck = deck_from_presentation(presentation)
    text = emit_json(deck) if fmt == "json" else emit_yaml(deck)

    def writer(handle) -> None:
        handle.write(text.encode("utf-8"))

    atomic_write(path, writer)
    return {"id": meta["id"], "path": str(path), "format": fmt}


def set_slide(target: str, slide: str, title, body, notes) -> dict:
    if title is None and body is None and notes is None:
        raise GdocsError("set-slide needs a title, body, or notes")
    for text in (title, body, notes):
        if isinstance(text, str) and len(text) > 50000:
            raise GdocsError("text exceeds 50000 characters")
    mode, value = check_slide_ref(slide)
    creds, drive = open_drive(write=True)
    meta = resolve(drive, "present", target)
    from gdocs import services

    service = _presentations(creds)
    presentation = services.execute(service.presentations().get(presentationId=meta["id"]))
    pages = presentation.get("slides") or []
    if mode == "index":
        if value > len(pages):
            raise GdocsError("slide was not found")
        page = pages[value - 1]
    else:
        page = next((item for item in pages if item.get("objectId") == value), None)
        if page is None:
            raise GdocsError("slide was not found")
    fields = {}
    if title is not None:
        fields["title"] = title
    if body is not None:
        fields["body"] = body
    if notes is not None:
        fields["notes"] = notes
    requests = plan_slide_writes(page, fields)
    services.execute(
        service.presentations().batchUpdate(
            presentationId=meta["id"],
            body={"requests": requests},
        )
    )
    return {"id": meta["id"], "slide": page.get("objectId")}


def _load(target: str, *, write: bool) -> dict:
    from gdocs import services

    creds, drive = open_drive(write=write)
    meta = resolve(drive, "present", target)
    return services.execute(_presentations(creds).presentations().get(presentationId=meta["id"]))


def _presentations(creds):
    from gdocs import services

    return services.build("slides", "v1", creds)


def _check_slide_text(title: str | None, body: str | None, notes: str | None = None) -> None:
    if not title and not body:
        raise GdocsError("add-slide needs a title or a body")
    for text in (title, body, notes):
        if text is not None and len(text) > 50000:
            raise GdocsError("text exceeds 50000 characters")


def _created_slide_id(response: dict) -> str:
    replies = response.get("replies") or []
    object_id = None
    if replies:
        object_id = (replies[0].get("createSlide") or {}).get("objectId")
    if not object_id:
        raise GdocsError("new slide was not created")
    return object_id


def _find_page(presentation: dict, object_id: str) -> dict:
    for slide in presentation.get("slides") or []:
        if slide.get("objectId") == object_id:
            return slide
    raise GdocsError("new slide was not created")


def _fill_deck(file_id: str, deck: dict) -> None:
    from gdocs import services

    creds, _drive = open_drive(write=True)
    service = _presentations(creds)
    presentation = services.execute(service.presentations().get(presentationId=file_id))
    originals = [check_object_id(slide.get("objectId") or "") for slide in presentation.get("slides") or []]
    slides = deck["slides"]
    created_ids: list[str] = []
    for start in range(0, len(slides), _CHUNK):
        batch = slides[start : start + _CHUNK]
        requests = [
            {"createSlide": {"slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"}}}
            for _slide in batch
        ]
        response = _slide_batch(service, file_id, requests)
        replies = response.get("replies") or []
        if len(replies) != len(requests):
            raise GdocsError("new slide was not created")
        for reply in replies:
            raw = (reply.get("createSlide") or {}).get("objectId")
            if not raw:
                raise GdocsError("new slide was not created")
            created_ids.append(check_object_id(raw))
    presentation = services.execute(service.presentations().get(presentationId=file_id))
    pages = {slide.get("objectId"): slide for slide in presentation.get("slides") or []}
    writes: list[dict] = []
    for object_id, slide in zip(created_ids, slides):
        page = pages.get(object_id)
        if page is None:
            raise GdocsError("new slide was not created")
        writes.extend(
            plan_slide_writes(page, slide, allow_empty=True, require_placeholders=False)
        )
    for start in range(0, len(writes), _CHUNK):
        chunk = writes[start : start + _CHUNK]
        if chunk:
            _slide_batch(service, file_id, chunk)
    deletes = plan_delete_slides(originals)
    for start in range(0, len(deletes), _CHUNK):
        chunk = deletes[start : start + _CHUNK]
        if chunk:
            _slide_batch(service, file_id, chunk)


def _slide_batch(service, presentation_id: str, requests: list[dict]) -> dict:
    from gdocs import services

    return services.execute(
        service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": requests},
        )
    )
