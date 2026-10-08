import pytest

from gdocs.driveq import (
    TAG_KEY,
    build_list_query,
    dump_tags,
    escape_drive_string,
    file_row,
    merge_tag_map,
    plan_share,
)
from gdocs.errors import GdocsError


def test_escape_order():
    assert escape_drive_string("a\\b'c") == "a\\\\b\\'c"


def test_name_query_escapes_quotes():
    query = build_list_query(kind="doc", name_contains="x' or name contains 'y")
    assert "contains 'x'" not in query
    assert "contains 'x\\' or name contains \\'y'" in query


def test_tag_query_is_comma_wrapped():
    query = build_list_query(kind="doc", tag="q1")
    assert ",q1," in query
    assert ",q10," not in query


def test_tag_budget():
    assert len(dump_tags(["a" * 64, "b" * 46]).encode("utf-8")) == 113
    with pytest.raises(GdocsError, match="113"):
        dump_tags(["a" * 64, "b" * 47])


def test_merge_keeps_other_keys_and_fails_closed():
    merged, changed = merge_tag_map({"other": "kept", TAG_KEY: ",q1,"}, add=("q2",))
    assert changed
    assert merged["other"] == "kept"
    assert merged[TAG_KEY] == ",q1,q2,"

    cleared, changed = merge_tag_map({"other": "kept", TAG_KEY: ",q1,"}, remove=("q1",))
    assert changed
    assert cleared[TAG_KEY] is None
    assert cleared["other"] == "kept"

    with pytest.raises(GdocsError, match="already set"):
        merge_tag_map({TAG_KEY: ",q1,"}, add=("q1",))
    with pytest.raises(GdocsError, match="is not set"):
        merge_tag_map({TAG_KEY: ",q1,"}, remove=("missing",))
    with pytest.raises(GdocsError):
        merge_tag_map({TAG_KEY: "nope!"}, add=("q1",))
    assert file_row({"appProperties": {TAG_KEY: "nope!"}, "id": "abc"})["tags"] == ""


def test_plan_share():
    with pytest.raises(GdocsError, match="refusing to share with anyone without --yes"):
        plan_share("anyone", "reader", False)
    body = plan_share("user:ada@example.com", "writer", True)
    assert body == {"type": "user", "role": "writer", "emailAddress": "ada@example.com"}
    anyone = plan_share("anyone", "reader", True)
    assert anyone["allowFileDiscovery"] is False
    with pytest.raises(GdocsError, match="role"):
        plan_share("user:ada@example.com", "owner", True)
    with pytest.raises(GdocsError, match="email"):
        plan_share("user:ada@localhost", "reader", True)
