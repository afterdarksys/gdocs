from gdocs.output import choose_output, render


def test_choose_output():
    assert choose_output(None, True) == "table"
    assert choose_output(None, False) == "json"
    assert choose_output("csv", True) == "csv"


def test_render_formats():
    table = render([["x" * 50]], "table")
    assert "…" in table
    assert "..." not in table
    assert "a b" in render([["a\nb"]], "table")
    assert "å" in render({"name": "å"}, "json")
    assert "\\u00e5" not in render({"name": "å"}, "json")
    assert render([], "json") == "[]\n"
    assert render([], "table") == ""
    assert render([], "csv") == ""
    assert render([], "ndjson") == ""
    rendered = render({"id": "abc"}, "json")
    assert rendered.endswith("\n")
    assert "\n  " in rendered
