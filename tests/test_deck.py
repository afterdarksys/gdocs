import json

import pytest

from gdocs.deck import (
    check_slide_ref,
    deck_from_presentation,
    emit_json,
    emit_yaml,
    load_deck,
    normalize_deck,
    parse_yaml_deck,
    plan_slide_writes,
    plan_text_requests,
    slide_to_record,
)
from gdocs.errors import GdocsError


def _element(object_id, kind, text):
    return {
        "objectId": object_id,
        "shape": {
            "placeholder": {"type": kind},
            "text": {"textElements": [{"textRun": {"content": text}}]},
        },
    }


def test_yaml_round_trip_keeps_plain_scalars():
    deck = {
        "title": "Deck",
        "slides": [
            {"title": "55555555", "body": "true", "notes": "ryan@foo.com"},
            {"title": "Hello\n\nWorld", "body": "01", "notes": "null"},
        ],
    }
    parsed = parse_yaml_deck(emit_yaml(deck))
    assert parsed == normalize_deck(deck)
    assert parsed["slides"][1]["title"] == "Hello\n\nWorld"


def test_yaml_chomps_trailing_newlines():
    deck = {"title": "Hello\n", "slides": [{"title": "\n", "body": "", "notes": ""}]}
    parsed = parse_yaml_deck(emit_yaml(normalize_deck(deck)))
    assert parsed["title"] == "Hello"
    assert parsed["slides"][0]["title"] == ""


def test_json_emit_keeps_a_trailing_newline():
    deck = normalize_deck({"title": "D", "slides": [{"title": "Hello\n"}]})
    loaded = json.loads(emit_json(deck))
    assert loaded["slides"][0]["title"] == "Hello\n"


def test_yaml_block_edges():
    notes = parse_yaml_deck(
        "title: Deck\nslides:\n  - body: |\n      Hello\n    notes: Say\n"
    )
    assert notes["slides"][0]["body"] == "Hello"
    assert notes["slides"][0]["notes"] == "Say"
    blank = parse_yaml_deck("title: Deck\nslides:\n  - body: |\n\n    notes: Say\n")
    assert blank["slides"][0]["body"] == ""
    one = parse_yaml_deck("title: Deck\nslides:\n  - body: |\n\n      Hello\n")
    assert one["slides"][0]["body"] == "\nHello"
    two = parse_yaml_deck("title: Deck\nslides:\n  - body: |\n\n\n      Hello\n")
    assert two["slides"][0]["body"] == "\n\nHello"
    internal = parse_yaml_deck("title: Deck\nslides:\n  - body: |\n      Hello\n\n      World\n")
    assert internal["slides"][0]["body"] == "Hello\n\nWorld"
    bang = parse_yaml_deck("title: Deck\nslides:\n  - body: |\n      Hello!\n")
    assert bang["slides"][0]["body"] == "Hello!"
    comment = parse_yaml_deck("# bang !\ntitle: Deck\nslides:\n")
    assert comment == {"title": "Deck", "slides": []}
    assert parse_yaml_deck('title: "hello!"\nslides:\n')["title"] == "hello!"


def test_yaml_rejects_unsafe_syntax():
    samples = {
        "title: !boom\nslides:\n": "yaml deck is invalid",
        "title: Deck\nslides: []\n": "yaml deck is invalid",
        "title:\nslides:\n": "yaml deck is invalid",
        "title: Hello: world\nslides:\n": "yaml deck is invalid",
        "title: Hello # no\nslides:\n": "yaml comment must be a full line",
        "title: !boom\n\tslides:\n": "yaml deck contains a tab",
        "title: A\ntitle: B\nslides:\n": "yaml deck has a duplicate key",
        "name: A\nslides:\n": "deck has an unknown key",
    }
    for text, message in samples.items():
        with pytest.raises(GdocsError, match=message):
            parse_yaml_deck(text)


def test_normalize_deck_fails_closed():
    assert len(normalize_deck({"title": "D", "slides": [{}] * 300})["slides"]) == 300
    with pytest.raises(GdocsError, match="deck has too many slides"):
        normalize_deck({"title": "D", "slides": [{}] * 301})
    with pytest.raises(GdocsError, match="deck has an unknown key"):
        normalize_deck({"id": "x", "title": "D", "slides": []})
    with pytest.raises(GdocsError, match="deck slide has an unknown key"):
        normalize_deck({"title": "D", "slides": [{"id": "p", "text": "hi"}]})
    with pytest.raises(GdocsError, match="deck title must be text"):
        normalize_deck({"title": None, "slides": []})
    with pytest.raises(GdocsError, match="deck needs slides"):
        normalize_deck({"title": "D"})
    with pytest.raises(GdocsError, match="slide text must be text"):
        normalize_deck({"title": "D", "slides": [{"title": 555}]})
    with pytest.raises(GdocsError, match="deck file must be json, yaml, or yml"):
        load_deck("missing.txt")


def test_slide_text_strips_one_newline():
    page = {
        "pageElements": [
            _element("c", "CENTERED_TITLE", "Centered\n"),
            _element("t", "TITLE", "A\n\nB\n"),
            _element("b", "BODY", "Hello\n\n"),
        ],
        "slideProperties": {
            "notesPage": {
                "pageElements": [
                    _element("num", "SLIDE_NUMBER", "1\n"),
                    _element("notes", "BODY", "Say\n"),
                ]
            }
        },
    }
    record = slide_to_record(page)
    assert record == {"title": "A\n\nB", "body": "Hello\n", "notes": "Say"}
    long_ok = _element("t", "TITLE", "x" * 50000 + "\n")
    assert slide_to_record({"pageElements": [long_ok]})["title"] == "x" * 50000
    with pytest.raises(GdocsError, match="text exceeds 50000 characters"):
        slide_to_record({"pageElements": [_element("t", "TITLE", "x" * 50001 + "\n")]})
    deck = deck_from_presentation({"title": None, "slides": []})
    assert deck == {"title": "", "slides": []}


def test_text_plans():
    assert plan_text_requests("box", "\n", "Hi") == [
        {"insertText": {"objectId": "box", "insertionIndex": 0, "text": "Hi"}}
    ]
    assert plan_text_requests("box", "Old\n", "New") == [
        {"deleteText": {"objectId": "box", "textRange": {"type": "ALL"}}},
        {"insertText": {"objectId": "box", "insertionIndex": 0, "text": "New"}},
    ]
    assert plan_text_requests("box", "\n", "") == []
    assert plan_text_requests("box", "Old\n", "") == [
        {"deleteText": {"objectId": "box", "textRange": {"type": "ALL"}}}
    ]
    page = {"pageElements": [_element("t", "TITLE", "\n")]}
    with pytest.raises(GdocsError, match="slide is missing a title placeholder"):
        plan_slide_writes({"pageElements": []}, {"title": "Hi"})
    with pytest.raises(GdocsError, match="edit changed nothing"):
        plan_slide_writes(page, {"title": ""})


def test_slide_refs():
    assert check_slide_ref("01") == ("index", 1)
    for spec in ("0", "0000", "12345", ""):
        with pytest.raises(GdocsError, match="slide was not found"):
            check_slide_ref(spec)
    with pytest.raises(GdocsError, match="slide id is invalid"):
        check_slide_ref("bad id")
