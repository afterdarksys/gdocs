"""Slides read, replace-all, and a title-and-body slide.

Threats: text is bounded before a request is sent. A new slide is rejected
when the layout has no matching placeholder, so a blank slide is not left
as a successful edit. Does not export thumbnails.
"""

from __future__ import annotations

from gdocs.drive_ops import open_drive, resolve
from gdocs.errors import GdocsError
from gdocs.extract import presentation_view, replace_request, require_text_changes


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


def add_slide(target: str, title: str | None, body: str | None) -> dict:
    _check_slide_text(title, body)
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
    object_id = _created_slide_id(created)
    presentation = services.execute(service.presentations().get(presentationId=meta["id"]))
    page = _find_page(presentation, object_id)
    requests = _placeholder_inserts(page, title, body)
    services.execute(
        service.presentations().batchUpdate(presentationId=meta["id"], body={"requests": requests})
    )
    return {"id": meta["id"], "slide": object_id}


def _load(target: str, *, write: bool) -> dict:
    from gdocs import services

    creds, drive = open_drive(write=write)
    meta = resolve(drive, "present", target)
    return services.execute(_presentations(creds).presentations().get(presentationId=meta["id"]))


def _presentations(creds):
    from gdocs import services

    return services.build("slides", "v1", creds)


def _check_slide_text(title: str | None, body: str | None) -> None:
    if not title and not body:
        raise GdocsError("add-slide needs a title or a body")
    for text in (title, body):
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


def _placeholder_type(element: dict) -> str | None:
    shape = element.get("shape") or {}
    placeholder = shape.get("placeholder") or element.get("placeholder") or {}
    return placeholder.get("type")


def _placeholder_inserts(page: dict, title: str | None, body: str | None) -> list[dict]:
    title_id = None
    body_id = None
    for element in page.get("pageElements") or []:
        kind = _placeholder_type(element)
        object_id = element.get("objectId")
        if kind in {"TITLE", "CENTERED_TITLE"} and title_id is None:
            title_id = object_id
        elif kind == "BODY" and body_id is None:
            body_id = object_id
    requests: list[dict] = []
    if title:
        if not title_id:
            raise GdocsError("slide is missing a title placeholder")
        requests.append({"insertText": {"objectId": title_id, "insertionIndex": 0, "text": title}})
    if body:
        if not body_id:
            raise GdocsError("slide is missing a body placeholder")
        requests.append({"insertText": {"objectId": body_id, "insertionIndex": 0, "text": body}})
    if not requests:
        raise GdocsError("slide is missing a title or body placeholder")
    return requests
