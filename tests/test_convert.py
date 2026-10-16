import pytest

from gdocs.convert import plan_convert
from gdocs.errors import GdocsError


def test_plan_convert_pairs():
    assert plan_convert("a.pdf", "b.docx") == ("doc", "pdf", "docx")
    assert plan_convert("a.csv", "b.pdf") == ("sheet", "csv", "pdf")
    assert plan_convert("notes.PPTX", "out.PDF") == ("present", "pptx", "pdf")


def test_plan_convert_refuses():
    for source, dest in (
        ("a.pdf", "b.pdf"),
        ("a.unknown", "b.unknown"),
        ("a.ods", "b.csv"),
        ("a.md", "b.xlsx"),
        ("a.json", "b.yaml"),
    ):
        with pytest.raises(GdocsError):
            plan_convert(source, dest)
    with pytest.raises(GdocsError, match="same type"):
        plan_convert("a.docx", "b.docx")
    with pytest.raises(GdocsError, match="not supported"):
        plan_convert("a.ods", "b.csv")


def test_plan_convert_ambiguous(monkeypatch):
    monkeypatch.setattr("gdocs.convert.import_types", lambda *_args, **_kwargs: ("a", "b"))
    monkeypatch.setattr("gdocs.convert.export_mime", lambda *_args, **_kwargs: "c")
    with pytest.raises(GdocsError, match="this conversion is ambiguous"):
        plan_convert("a.foo", "b.bar")
