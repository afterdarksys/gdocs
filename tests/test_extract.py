import pytest

from gdocs.errors import GdocsError
from gdocs.extract import (
    append_location,
    document_text,
    presentation_view,
    replace_request,
    require_text_changes,
    simplified_doc,
)


def _doc():
    return {
        "documentId": "doc-id",
        "title": "Demo",
        "tabs": [
            {
                "tabProperties": {"title": "Main", "tabId": "t1"},
                "documentTab": {
                    "body": {
                        "content": [
                            {
                                "endIndex": 10,
                                "paragraph": {
                                    "paragraphStyle": {"namedStyleType": "HEADING_1"},
                                    "elements": [{"textRun": {"content": "Hello\n"}}],
                                },
                            },
                            {
                                "endIndex": 10,
                                "table": {
                                    "tableRows": [
                                        {
                                            "tableCells": [
                                                {
                                                    "content": [
                                                        {
                                                            "paragraph": {
                                                                "elements": [{"textRun": {"content": "A\n"}}]
                                                            }
                                                        }
                                                    ]
                                                },
                                                {
                                                    "content": [
                                                        {
                                                            "paragraph": {
                                                                "elements": [{"textRun": {"content": "B\n"}}]
                                                            }
                                                        }
                                                    ]
                                                },
                                            ]
                                        }
                                    ]
                                }
                            },
                        ]
                    }
                },
            }
        ],
    }


def test_doc_markdown_and_simplified_shape():
    text = document_text(_doc(), markdown=True)
    assert "# Main" in text
    assert "# Hello" in text
    assert "A\tB" in text
    view = simplified_doc(_doc())
    assert set(view) == {"id", "title", "body"}


def test_slide_notes_keep_body():
    presentation = {
        "presentationId": "pres",
        "title": "Deck",
        "slides": [
            {
                "objectId": "slide-1",
                "pageElements": [],
                "slideProperties": {
                    "notesPage": {
                        "pageElements": [
                            {
                                "shape": {
                                    "placeholder": {"type": "BODY"},
                                    "text": {"textElements": [{"textRun": {"content": "Speaker"}}]},
                                }
                            },
                            {
                                "shape": {
                                    "placeholder": {"type": "SLIDE_NUMBER"},
                                    "text": {"textElements": [{"textRun": {"content": "3"}}]},
                                }
                            },
                        ]
                    }
                },
            }
        ],
    }
    notes = presentation_view(presentation)["slides"][0]["notes"]
    assert "Speaker" in notes
    assert "3" not in notes


def test_append_location_uses_api_index():
    located = append_location(_doc())
    assert located == {"index": 9, "tabId": "t1"}
    assert located["index"] != 0
    early = {
        "body": {"content": [{"endIndex": 2}]},
    }
    assert append_location(early) == {"index": 1}
    with pytest.raises(GdocsError):
        append_location({"body": {"content": [{"endIndex": 1}]}})


def test_replace_must_change_text():
    with pytest.raises(GdocsError, match="empty"):
        replace_request("", "new")
    with pytest.raises(GdocsError, match="changed nothing"):
        require_text_changes({"replies": [{"replaceAllText": {"occurrencesChanged": 0}}]})
