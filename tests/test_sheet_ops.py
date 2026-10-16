import pytest

from gdocs.errors import GdocsError
from gdocs.sheet_ops import _column_payload, _payload, _rows_under_header


def test_values_accept_one_object():
    kind, payload = _payload('{"name":"Ryan","email":"ryan@foo.com"}', None)
    assert kind == "objects"
    assert payload == [{"name": "Ryan", "email": "ryan@foo.com"}]
    kind, payload = _payload('[["Ada","ada@example.com"]]', None)
    assert kind == "grid"
    assert payload == [["Ada", "ada@example.com"]]


def test_payload_requires_one_source():
    with pytest.raises(GdocsError, match="pass one of --values or --json"):
        _payload(None, None)
    with pytest.raises(GdocsError, match="pass one of --values or --json"):
        _payload("[]", "rows.json")


def test_column_objects_are_rejected():
    with pytest.raises(GdocsError, match="column values must be one column"):
        _column_payload('{"name":"Ryan"}', None)


def test_rows_under_header_do_not_reread_the_header():
    rows = _rows_under_header(["name", "email"], "grid", [["Ada", "a@b.com"], ["Bo"]])
    assert rows == [["Ada", "a@b.com"], ["Bo", ""]]
    with pytest.raises(GdocsError, match="row is wider than the columns"):
        _rows_under_header(["name"], "grid", [["a", "b"]])
    with pytest.raises(GdocsError, match="json row has unknown columns"):
        _rows_under_header(["name"], "objects", [{"email": "a@b.com"}])
