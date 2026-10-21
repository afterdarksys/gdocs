"""Argument parsing for gdocs.

Google client libraries are imported by the command handlers, so ``--help``
stays on the standard library.
"""

from __future__ import annotations

import argparse
import sys

from gdocs.errors import GdocsError, report_exception

_OUTPUTS = ("table", "json", "ndjson", "csv", "plain")


def build_parser() -> argparse.ArgumentParser:
    """Build a fresh parser. Parents are created here so this can run twice."""

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--output", choices=_OUTPUTS, default=None)
    common.add_argument("--limit", type=int, default=None)
    tab = argparse.ArgumentParser(add_help=False)
    tab.add_argument("--tab", default=None)

    parser = argparse.ArgumentParser(
        prog="gdocs",
        description="Command line for Google Docs, Sheets, and Slides",
    )
    nouns = parser.add_subparsers(dest="noun", required=True)
    setup = nouns.add_parser("setup", help="walk through Google Cloud setup and sign in")
    setup.add_argument("--client", help="skip the guide and use this Desktop OAuth client JSON")
    setup.add_argument("--readonly", action="store_true", help="request read-only access")
    setup.set_defaults(func=_cmd_setup, kind=None)
    login = nouns.add_parser("login", help="store an OAuth refresh token")
    login.add_argument("--client", required=True, help="Desktop OAuth client JSON")
    login.add_argument("--readonly", action="store_true")
    login.add_argument("--output", choices=_OUTPUTS, default=None)
    login.set_defaults(func=_cmd_login, kind=None)

    logout = nouns.add_parser("logout", help="delete the stored token")
    logout.add_argument("--output", choices=_OUTPUTS, default=None)
    logout.set_defaults(func=_cmd_logout, kind=None)

    status = nouns.add_parser("status", help="show the signed-in account")
    status.add_argument("--output", choices=_OUTPUTS, default=None)
    status.set_defaults(func=_cmd_status, kind=None)

    for name in ("doc", "docs"):
        _add_editor(nouns, name, "doc", common)
    for name in ("sheet", "sheets"):
        _add_sheet(nouns, name, common, tab)
    for name in ("present", "presents", "slides"):
        _add_editor(nouns, name, "present", common)
    convert = nouns.add_parser(
        "convert",
        parents=[common],
        help="import a file and export it as another format",
    )
    convert.add_argument("source")
    convert.add_argument("dest")
    convert.add_argument("--force", action="store_true")
    convert.add_argument("--keep", action="store_true")
    convert.set_defaults(func=_cmd_convert, kind=None)
    from gdocs.work_cli import register
    register(nouns, common)
    return parser


def _add_editor(nouns: argparse._SubParsersAction, name: str, kind: str, common) -> None:
    parser = nouns.add_parser(name)
    parser.set_defaults(kind=kind)
    verbs = parser.add_subparsers(dest="verb", required=True)
    from gdocs.work_cli import register_editor
    register_editor(verbs, kind, common)
    _add_list_find_search(verbs, kind, common)
    created = _leaf(verbs, "create", [common], _cmd_create, kind)
    created.add_argument("--name", required=True)
    if kind == "doc":
        created.add_argument("--text", default=None)
    else:
        created.add_argument("--deck", default=None)

    view = _leaf(verbs, "view", [common], _cmd_view, kind)
    view.add_argument("target")
    if kind == "doc":
        view.add_argument("--format", dest="fmt", choices=("md", "text", "json"), default="json")
    view.add_argument("--raw", action="store_true")

    edit = verbs.add_parser("edit")
    edit.add_argument("target")
    edits = edit.add_subparsers(dest="edit_cmd", required=True)
    replace = _leaf(edits, "replace", [common], _cmd_replace, kind)
    replace.add_argument("old")
    replace.add_argument("new")
    if kind == "doc":
        append = _leaf(edits, "append", [common], _cmd_append, kind)
        append.add_argument("text")
    else:
        slide = _leaf(edits, "add-slide", [common], _cmd_add_slide, kind)
        slide.add_argument("--title", default=None)
        slide.add_argument("--body", default=None)
        slide.add_argument("--notes", default=None)
        setter = _leaf(edits, "set-slide", [common], _cmd_set_slide, kind)
        setter.add_argument("--slide", required=True)
        setter.add_argument("--title", default=None)
        setter.add_argument("--body", default=None)
        setter.add_argument("--notes", default=None)

    tag = _leaf(verbs, "tag", [common], _cmd_tag, kind)
    tag.add_argument("target")
    tag.add_argument("tag_cmd", choices=("add", "rm", "list"))
    tag.add_argument("tags", nargs="*")

    share = _leaf(verbs, "share", [common], _cmd_share, kind)
    share.add_argument("target")
    share.add_argument("who", nargs="?")
    share.add_argument("role", nargs="?")
    share.add_argument("--yes", action="store_true")

    _add_export(verbs, kind, common)
    imported = _leaf(verbs, "import", [common], _cmd_import, kind)
    imported.add_argument("path")
    imported.add_argument("--name", default=None)


def _add_sheet(nouns: argparse._SubParsersAction, name: str, common, tab) -> None:
    parser = nouns.add_parser(name)
    parser.set_defaults(kind="sheet")
    verbs = parser.add_subparsers(dest="verb", required=True)
    from gdocs.work_cli import register_sheet
    register_sheet(verbs, common, tab)
    _add_list_find_search(verbs, "sheet", common)
    _add_export(verbs, "sheet", common)
    created = _leaf(verbs, "create", [common, tab], _cmd_sheet_create, "sheet")
    created.add_argument("--name", required=True)
    created.add_argument("--columns", required=True)
    created.add_argument("--values", default=None)
    created.add_argument("--json", dest="json_path", default=None)

    view = _leaf(verbs, "view", [common, tab], _cmd_sheet_view, "sheet")
    view.add_argument("target")
    view.add_argument("--head", type=int, default=None)
    view.add_argument("--raw", action="store_true")

    update = _leaf(verbs, "update", [common, tab], _cmd_update, "sheet")
    update.add_argument("target")
    update.add_argument("range_a1", nargs="?", metavar="RANGE")
    update.add_argument("--values", default=None)
    update.add_argument("--json", dest="json_path", default=None)
    update.add_argument("--append", action="store_true")
    update.add_argument("--raw", action="store_true")
    update.add_argument("--formula", action="store_true")

    cell = _leaf(verbs, "edit-cell", [common, tab], _cmd_edit_cell, "sheet")
    cell.add_argument("target")
    cell.add_argument("--cell", required=True)
    cell.add_argument("--value", default=None)
    cell.add_argument("--formula", default=None)
    cell.add_argument("--raw", action="store_true")

    row = _leaf(verbs, "edit-row", [common, tab], _cmd_edit_row, "sheet")
    row.add_argument("target")
    row.add_argument("--row", type=int, default=None)
    row.add_argument("--values", default=None)
    row.add_argument("--json", dest="json_path", default=None)
    row.add_argument("--where", default=None)
    row.add_argument("--set", dest="sets", action="append")
    row.add_argument("--insert", type=int, default=None)
    row.add_argument("--delete", type=int, default=None)
    row.add_argument("--all", action="store_true")
    row.add_argument("--yes", action="store_true")
    row.add_argument("--raw", action="store_true")
    row.add_argument("--formula", action="store_true")

    column = _leaf(verbs, "edit-col", [common, tab], _cmd_edit_col, "sheet")
    column.add_argument("target")
    column.add_argument("--col", default=None)
    column.add_argument("--from", dest="source", default=None)
    column.add_argument("--values", default=None)
    column.add_argument("--json", dest="json_path", default=None)
    column.add_argument("--insert", action="store_true")
    column.add_argument("--at", default=None)
    column.add_argument("--header", default=None)
    column.add_argument("--delete", action="store_true")
    column.add_argument("--rename", default=None)
    column.add_argument("--yes", action="store_true")
    column.add_argument("--raw", action="store_true")
    column.add_argument("--formula", action="store_true")

    filtered = _leaf(verbs, "filter", [common, tab], _cmd_filter, "sheet")
    filtered.add_argument("target")
    filtered.add_argument("--where", required=True)
    filtered.add_argument("--apply", action="store_true")

    extracted = _leaf(verbs, "extract", [common, tab], _cmd_extract, "sheet")
    extracted.add_argument("target")
    extracted.add_argument("--cols", required=True)
    extracted.add_argument("--where", default=None)

    as_json = _leaf(verbs, "json", [common, tab], _cmd_json, "sheet")
    as_json.add_argument("target")

    imported = _leaf(verbs, "import", [common, tab], _cmd_import, "sheet")
    imported.add_argument("path")
    imported.add_argument("--name", default=None)
    imported.add_argument("--into", default=None)
    imported.add_argument("--replace", action="store_true")


def _add_list_find_search(verbs, kind: str, common) -> None:
    listing = _leaf(verbs, "list", [common], _cmd_list, kind)
    listing.add_argument("--recursive", action="store_true")
    listing.add_argument("--query", default=None)
    listing.add_argument("--tag", default=None)
    listing.add_argument("--starred", action="store_true")

    find = _leaf(verbs, "find", [common], _cmd_find, kind)
    find.add_argument("--recursive", action="store_true")
    find.add_argument("query")
    find.add_argument("--tag", default=None)
    find.add_argument("--starred", action="store_true")

    search = _leaf(verbs, "search", [common], _cmd_search, kind)
    search.add_argument("--recursive", action="store_true")
    search.add_argument("text")
    search.add_argument("--snippets", type=int, default=5)


def _add_export(verbs, kind: str, common) -> None:
    export = _leaf(verbs, "export", [common], _cmd_export, kind)
    export.add_argument("target")
    export.add_argument("fmt")
    export.add_argument("dest")
    export.add_argument("--force", action="store_true")


def _leaf(verbs, name: str, parents: list, func, kind: str):
    parser = verbs.add_parser(name, parents=parents)
    parser.set_defaults(func=func, kind=kind)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        if code is None or code == 0:
            return 0
        if isinstance(code, int):
            return code
        return 2
    try:
        import os
        if os.environ.get("GDOCS_CI") == "1" and args.noun in ("login", "setup"):
            raise GdocsError("interactive authentication is disabled in CI; configure ADC or stored credentials", 4)
        result = args.func(args)
        _show(result, args)
        return getattr(result, "exit_code", 0)
    except SystemExit:
        raise
    except BaseException as exc:
        return report_exception(exc)
    return 0


def _show(result, args) -> None:
    if result is None:
        return
    if isinstance(result, str):
        sys.stdout.write(result if result.endswith("\n") else result + "\n")
        return
    from gdocs.driveq import FILE_COLUMNS
    from gdocs.output import emit

    columns = None
    row = result[0] if isinstance(result, list) and result else result
    if isinstance(row, dict) and "webViewLink" in row:
        columns = list(FILE_COLUMNS)
        if "snippet" in row:
            columns.append("snippet")
    emit(result, getattr(args, "output", None), columns=columns)


def _cmd_setup(args):
    from gdocs.setup import run_setup

    return run_setup(args.client, args.readonly)


def _cmd_login(args):
    from gdocs.auth import cmd_login

    cmd_login(args)
    return None


def _cmd_logout(args):
    from gdocs.auth import cmd_logout

    cmd_logout(args)
    return None


def _cmd_status(args):
    from gdocs.auth import cmd_status

    cmd_status(args)
    return None


def _cmd_list(args):
    from gdocs.drive_ops import list_files

    return list_files(
        args.kind,
        recursive=args.recursive,
        name_contains=args.query,
        tag=args.tag,
        starred=args.starred,
        limit=args.limit,
    )


def _cmd_find(args):
    from gdocs.drive_ops import find_files

    return find_files(args.kind, args.query, tag=args.tag, starred=args.starred, limit=args.limit, recursive=args.recursive)


def _cmd_search(args):
    from gdocs.drive_ops import search_files

    return search_files(args.kind, args.text, limit=args.limit, snippets=args.snippets, recursive=args.recursive)


def _cmd_view(args):
    if args.kind == "present":
        from gdocs.slide_ops import view

        return view(args.target, raw=args.raw)
    from gdocs.doc_ops import view

    return view(args.target, fmt=args.fmt, raw=args.raw)


def _cmd_replace(args):
    if args.kind == "present":
        from gdocs.slide_ops import replace_text
    else:
        from gdocs.doc_ops import replace_text
    return replace_text(args.target, args.old, args.new)


def _cmd_append(args):
    from gdocs.doc_ops import append_text

    return append_text(args.target, args.text)


def _cmd_create(args):
    if args.kind == "doc":
        from gdocs.doc_ops import create

        return create(args.name, text=args.text)
    from gdocs.deck import load_deck
    from gdocs.slide_ops import create

    deck = load_deck(args.deck) if args.deck else None
    return create(args.name, deck=deck)


def _cmd_add_slide(args):
    from gdocs.slide_ops import add_slide

    return add_slide(args.target, args.title, args.body, notes=args.notes)


def _cmd_set_slide(args):
    from gdocs.slide_ops import set_slide

    return set_slide(args.target, args.slide, args.title, args.body, args.notes)


def _cmd_tag(args):
    tags = list(args.tags or [])
    if args.tag_cmd == "list":
        if tags:
            raise GdocsError("tag list does not take tag names")
        from gdocs.drive_ops import tag_list

        return tag_list(args.kind, args.target)
    if not tags:
        raise GdocsError("missing tag")
    if args.tag_cmd == "add":
        from gdocs.drive_ops import tag_add

        return tag_add(args.kind, args.target, tags)
    from gdocs.drive_ops import tag_remove

    return tag_remove(args.kind, args.target, tags)


def _cmd_share(args):
    who = args.who
    role = args.role
    if who not in (None, "", "list", "revoke"):
        from gdocs.driveq import plan_share

        plan_share(who, role or "", bool(args.yes))
    from gdocs.drive_ops import share

    return share(args.kind, args.target, who, role, bool(args.yes))


def _cmd_export(args):
    if args.kind == "present" and args.fmt in {"json", "yaml", "yml"}:
        from gdocs.slide_ops import export_deck

        return export_deck(args.target, args.fmt, args.dest, args.force)
    from gdocs.drive_ops import export_file

    return export_file(args.kind, args.target, args.fmt, args.dest, args.force)


def _cmd_import(args):
    from pathlib import Path

    path = args.path
    suffix = Path(path).suffix.lower()
    into = getattr(args, "into", None)
    replace = bool(getattr(args, "replace", False))
    if args.kind == "sheet" and suffix == ".json" and (into or replace):
        raise GdocsError("json import creates a new spreadsheet")
    if replace and not into:
        raise GdocsError("--replace needs --into")
    if into:
        if not replace:
            raise GdocsError("--replace is required")
        from gdocs.sheet_ops import import_csv

        return import_csv(into, path, tab=getattr(args, "tab", None), replace=True)
    if args.kind == "sheet" and suffix == ".json":
        from gdocs.sheet_ops import import_records

        return import_records(path, name=args.name, tab=getattr(args, "tab", None))
    if args.kind == "present" and suffix in {".json", ".yaml", ".yml"}:
        from gdocs.slide_ops import import_deck

        return import_deck(path, name=args.name)
    from gdocs.drive_ops import import_file

    return import_file(args.kind, path, name=args.name)


def _cmd_convert(args):
    from gdocs.convert import convert

    return convert(args.source, args.dest, args.force, args.keep)


def _cmd_sheet_create(args):
    from gdocs.sheet_ops import create_sheet

    return create_sheet(
        args.name,
        args.columns,
        values=args.values,
        json_path=args.json_path,
        tab=args.tab,
    )


def _cmd_sheet_view(args):
    from gdocs.sheet_ops import view

    return view(args.target, tab=args.tab, head=args.head, raw=args.raw, limit=args.limit)


def _cmd_update(args):
    from gdocs.sheet_ops import update

    return update(
        args.target,
        args.range_a1,
        values=args.values,
        json_path=args.json_path,
        append=args.append,
        raw=args.raw,
        formula=args.formula,
        tab=args.tab,
    )


def _cmd_edit_cell(args):
    from gdocs.sheet_ops import edit_cell

    return edit_cell(
        args.target,
        cell=args.cell,
        value=args.value,
        formula=args.formula,
        raw=args.raw,
        tab=args.tab,
    )


def _cmd_edit_row(args):
    if args.delete is not None and not args.yes:
        from gdocs.grid import plan_delete

        plan_delete(0, "ROWS", args.delete, False)
    from gdocs.sheet_ops import edit_row

    return edit_row(
        args.target,
        row=args.row,
        values=args.values,
        json_path=args.json_path,
        where=args.where,
        sets=args.sets,
        insert=args.insert,
        delete=args.delete,
        all_matches=args.all,
        yes=args.yes,
        raw=args.raw,
        formula=args.formula,
        tab=args.tab,
        limit=args.limit,
    )


def _cmd_edit_col(args):
    if args.delete and not args.yes:
        from gdocs.grid import plan_delete

        plan_delete(0, "COLUMNS", 1, False)
    from gdocs.sheet_ops import edit_col

    return edit_col(
        args.target,
        col=args.col,
        source=args.source,
        values=args.values,
        json_path=args.json_path,
        insert=args.insert,
        at=args.at,
        header=args.header,
        delete=args.delete,
        rename=args.rename,
        yes=args.yes,
        raw=args.raw,
        formula=args.formula,
        tab=args.tab,
    )


def _cmd_filter(args):
    from gdocs.sheet_ops import filter_sheet

    return filter_sheet(args.target, where=args.where, apply=args.apply, tab=args.tab, limit=args.limit)


def _cmd_extract(args):
    from gdocs.sheet_ops import extract

    return extract(args.target, cols=args.cols, where=args.where, tab=args.tab, limit=args.limit)


def _cmd_json(args):
    from gdocs.sheet_ops import as_json

    return as_json(args.target, tab=args.tab, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
