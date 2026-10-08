"""Plain text and light Markdown from Docs and Slides API payloads."""

from __future__ import annotations

from gdocs.errors import GdocsError

_HEADING = {
    "TITLE": "# ",
    "HEADING_1": "# ",
    "HEADING_2": "## ",
    "HEADING_3": "### ",
    "HEADING_4": "#### ",
    "HEADING_5": "##### ",
    "HEADING_6": "###### ",
}


def document_text(document: dict, *, markdown: bool = False) -> str:
    chunks: list[str] = []
    tabs = document.get("tabs") or []
    if tabs:
        for tab in tabs:
            _walk_tab(tab, chunks, markdown)
    else:
        chunks.append(_body_text(document.get("body") or {}, markdown))
    return "\n".join(chunk for chunk in chunks if chunk)


def simplified_doc(document: dict, *, markdown: bool = False) -> dict:
    return {
        "id": document.get("documentId"),
        "title": document.get("title"),
        "body": document_text(document, markdown=markdown),
    }


def append_location(document: dict) -> dict:
    tabs = document.get("tabs") or []
    if tabs:
        tab = tabs[0]
        tab_id = (tab.get("tabProperties") or {}).get("tabId")
        body = (tab.get("documentTab") or {}).get("body") or {}
        location = {"index": _end_index(body)}
        if tab_id:
            location["tabId"] = tab_id
        return location
    return {"index": _end_index(document.get("body") or {})}


def replace_request(old: str, new: str) -> dict:
    if not isinstance(old, str) or old == "":
        raise GdocsError("refusing to replace empty text")
    if not isinstance(new, str):
        raise GdocsError("replacement text is missing")
    if len(old) > 50000 or len(new) > 50000:
        raise GdocsError("text exceeds 50000 characters")
    return {
        "replaceAllText": {
            "containsText": {"text": old, "matchCase": True},
            "replaceText": new,
        }
    }


def require_text_changes(response: dict) -> int:
    total = 0
    for reply in response.get("replies") or []:
        block = reply.get("replaceAllText") or {}
        total += int(block.get("occurrencesChanged") or 0)
    if total <= 0:
        raise GdocsError("edit changed nothing")
    return total


def presentation_view(presentation: dict) -> dict:
    slides = []
    for slide in presentation.get("slides") or []:
        slides.append(
            {
                "id": slide.get("objectId"),
                "text": _page_text(slide),
                "notes": _notes_text(slide),
            }
        )
    return {
        "id": presentation.get("presentationId"),
        "title": presentation.get("title"),
        "slides": slides,
    }


def snippet_around(text: str, query: str, width: int = 160) -> str:
    if not text or not query:
        return ""
    at = text.casefold().find(query.casefold())
    if at < 0:
        return ""
    start = max(0, at - 40)
    end = min(len(text), at + len(query) + width)
    return text[start:end].replace("\n", " ")


def _walk_tab(tab: dict, chunks: list[str], markdown: bool) -> None:
    title = (tab.get("tabProperties") or {}).get("title")
    if title:
        chunks.append(f"# {title}" if markdown else str(title))
    body = (tab.get("documentTab") or {}).get("body") or {}
    chunks.append(_body_text(body, markdown))
    for child in tab.get("childTabs") or []:
        _walk_tab(child, chunks, markdown)


def _body_text(body: dict, markdown: bool) -> str:
    blocks: list[str] = []
    for element in body.get("content") or []:
        if "paragraph" in element:
            blocks.append(_paragraph(element["paragraph"], markdown))
        elif "table" in element:
            blocks.append(_table(element["table"]))
        elif "tableOfContents" in element:
            blocks.append(_body_text(element["tableOfContents"], markdown))
    return "\n".join(block for block in blocks if block)


def _paragraph(paragraph: dict, markdown: bool) -> str:
    parts: list[str] = []
    for element in paragraph.get("elements") or []:
        run = element.get("textRun")
        if run and run.get("content"):
            parts.append(run["content"])
    raw = "".join(parts)
    if raw.endswith("\n"):
        raw = raw[:-1]
    if raw == "":
        return ""
    style = (paragraph.get("paragraphStyle") or {}).get("namedStyleType") or ""
    if markdown and style in _HEADING:
        return _HEADING[style] + raw
    if markdown and paragraph.get("bullet"):
        return "- " + raw
    return raw


def _table(table: dict) -> str:
    lines: list[str] = []
    for row in table.get("tableRows") or []:
        cells: list[str] = []
        for cell in row.get("tableCells") or []:
            text = _body_text({"content": cell.get("content") or []}, markdown=False)
            cells.append(text.replace("\n", " ").strip())
        lines.append("\t".join(cells))
    return "\n".join(lines)


def _end_index(body: dict) -> int:
    content = body.get("content") or []
    if not content:
        raise GdocsError("document has no body")
    end = content[-1].get("endIndex")
    if not isinstance(end, int) or end < 2:
        raise GdocsError("document end index is unusable")
    # Docs indexes are UTF-16 and already computed by the API. The last
    # index belongs to the trailing newline, so insert before it, never at 0.
    return end - 1


def _page_text(page: dict) -> str:
    parts: list[str] = []
    for element in page.get("pageElements") or []:
        _element_text(element, parts)
    return "\n".join(part for part in parts if part)


def _element_text(element: dict, parts: list[str]) -> None:
    if "shape" in element:
        text = _shape_runs(element["shape"])
        if text:
            parts.append(text)
    elif "table" in element:
        lines: list[str] = []
        for row in element["table"].get("tableRows") or []:
            cells = []
            for cell in row.get("tableCells") or []:
                cell_parts: list[str] = []
                _element_text({"shape": {"text": cell.get("text") or {}}}, cell_parts)
                cells.append(" ".join(cell_parts))
            lines.append("\t".join(cells))
        if lines:
            parts.append("\n".join(lines))
    elif "elementGroup" in element:
        for child in element["elementGroup"].get("children") or []:
            _element_text(child, parts)


def _shape_runs(shape: dict) -> str:
    parts: list[str] = []
    for element in (shape.get("text") or {}).get("textElements") or []:
        run = element.get("textRun")
        if run and run.get("content"):
            parts.append(run["content"])
    return "".join(parts).strip()


def _notes_text(slide: dict) -> str:
    notes = (slide.get("slideProperties") or {}).get("notesPage") or {}
    bodies: list[str] = []
    others: list[str] = []
    for element in notes.get("pageElements") or []:
        if "shape" not in element:
            continue
        placeholder = ((element.get("shape") or {}).get("placeholder") or {}).get("type")
        text = _shape_runs(element["shape"])
        if not text:
            continue
        if placeholder == "BODY":
            bodies.append(text)
        elif placeholder not in {"SLIDE_IMAGE", "SLIDE_NUMBER"}:
            others.append(text)
    return "\n".join(bodies or others)
