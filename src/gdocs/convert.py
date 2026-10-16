"""Import a file through Drive and export it as another format.

Threats: the destination is checked before an intermediate file is created.
The same suffix is refused. The intermediate is trashed unless --keep.
A failed export trashes the intermediate too. Does not parse Office or PDF
locally.
"""

from __future__ import annotations

from pathlib import Path

from gdocs.driveq import export_mime, import_types
from gdocs.errors import GdocsError
from gdocs.filesafe import check_import_file, prepare_output

_KINDS = ("doc", "sheet", "present")


def plan_convert(source: str, dest: str) -> tuple[str, str, str]:
    src = Path(source).suffix.lower().lstrip(".")
    dst = Path(dest).suffix.lower().lstrip(".")
    if src == dst:
        raise GdocsError("source and destination have the same type")
    matches = []
    for kind in _KINDS:
        try:
            import_types(kind, src)
            export_mime(kind, dst)
        except GdocsError:
            continue
        matches.append(kind)
    if not matches:
        raise GdocsError("this conversion is not supported")
    if len(matches) > 1:
        raise GdocsError("this conversion is ambiguous")
    return matches[0], src, dst


def convert(source: str, dest: str, force: bool, keep: bool) -> dict:
    kind, _src, fmt = plan_convert(source, dest)
    check_import_file(Path(source))
    prepare_output(Path(dest), force)
    from gdocs.drive_ops import abandon, export_file, import_file, trash_file

    created = import_file(kind, source)
    file_id = created.get("id") or ""
    try:
        exported = export_file(kind, file_id, fmt, dest, force)
    except Exception as exc:
        abandon(file_id, exc)
    trashed = False
    if not keep:
        try:
            trash_file(file_id)
            trashed = True
        except Exception:
            trashed = False
    return {"id": file_id, "path": exported["path"], "format": fmt, "kind": kind, "trashed": trashed}
