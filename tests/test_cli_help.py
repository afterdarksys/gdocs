import pytest

from gdocs.cli import build_parser, main


def test_help_and_unknown_noun(capsys):
    assert main(["--help"]) == 0
    assert main(["convert", "--help"]) == 0
    assert main(["doc", "--help"]) == 0
    for name in ("docs", "sheet", "sheets", "present", "presents", "slides"):
        assert main([name, "--help"]) == 0
    assert main(["nope"]) == 2
    capsys.readouterr()


def test_edit_parse_shape():
    build_parser()
    args = build_parser().parse_args(["doc", "edit", "FILEID", "replace", "old", "new"])
    assert args.target == "FILEID"
    assert args.old == "old"
    assert args.new == "new"
    assert args.kind == "doc"
    assert args.verb == "edit"
    assert args.edit_cmd == "replace"
    flagged = build_parser().parse_args(
        ["doc", "edit", "FILEID", "replace", "old", "new", "--output", "json"]
    )
    assert flagged.output == "json"


def test_delete_and_public_share_never_build(capsys, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("build was called")

    monkeypatch.setattr("gdocs.services.build", boom)

    row = main(["sheet", "edit-row", "Budget", "--delete", "4"])
    row_err = capsys.readouterr().err
    assert row == 1
    assert "refusing to delete" in row_err
    assert "unexpected error" not in row_err

    column = main(["sheet", "edit-col", "Budget", "--delete"])
    column_err = capsys.readouterr().err
    assert column == 1
    assert "refusing to delete" in column_err
    assert "unexpected error" not in column_err

    share = main(["doc", "share", "Budget", "anyone", "writer"])
    share_err = capsys.readouterr().err
    assert share == 1
    assert "refusing to share with anyone" in share_err
    assert "unexpected error" not in share_err


def test_local_writes_never_build(capsys, monkeypatch, tmp_path):
    def boom(*_args, **_kwargs):
        raise AssertionError("build was called")

    monkeypatch.setattr("gdocs.services.build", boom)

    def expect(argv, message):
        code = main(argv)
        err = capsys.readouterr().err
        assert code == 1
        assert message in err
        assert "unexpected error" not in err

    expect(["convert", "a.docx", "b.docx"], "source and destination have the same type")
    source = tmp_path / "a.docx"
    source.write_bytes(b"docx")
    dest = tmp_path / "a.pdf"
    dest.write_bytes(b"pdf")
    expect([ "convert", str(source), str(dest)], "already exists")
    expect(
        ["sheet", "create", "--name", "Leads", "--columns", "name,name"],
        "duplicate header names",
    )
    expect(["doc", "create", "--name", "a\nb"], "name is invalid")
    expect(
        ["present", "edit", "FILE", "set-slide", "--slide", "1"],
        "set-slide needs a title, body, or notes",
    )
    deck = tmp_path / "deck.yaml"
    deck.write_text("title: !boom\nslides:\n", encoding="utf-8")
    expect(
        ["present", "create", "--name", "Deck", "--deck", str(deck)],
        "yaml deck is invalid",
    )
    expect(
        ["sheet", "import", "rows.json", "--into", "FILE", "--replace"],
        "json import creates a new spreadsheet",
    )


def test_filter_requires_login(capsys):
    code = main(["sheet", "filter", "Budget", "--where", "status=open"])
    err = capsys.readouterr().err
    assert code == 1
    assert "not logged in" in err
    assert "ya29" not in err
