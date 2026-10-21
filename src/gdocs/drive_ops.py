"""Drive listing, name resolution, tags, sharing, export, import, and blank files.

Threats: user text is escaped before it is placed in a Drive query. Writes
require the full drive scope. A public share is planned before a client is
built. Export refuses a symlink destination before any download. Does not
protect a file an attacker can already open in Drive.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NoReturn

from gdocs.driveq import (
    FILE_FIELDS,
    KIND_MIME,
    LIST_FIELDS,
    _ID,
    build_list_query,
    check_tag,
    export_mime,
    extract_id,
    file_row,
    import_types,
    merge_tag_map,
    plan_share,
)
from gdocs.errors import GdocsError
from gdocs.extract import snippet_around
from gdocs.filesafe import (
    MAX_EXPORT_BYTES,
    MAX_IMPORT_BYTES,
    atomic_write,
    prepare_output,
    stage_regular_file,
)
from gdocs.grid import list_limit

_SNIPPET_BYTES = 2 * 1024 * 1024
_PERM_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SHARE_FIELDS = "id,type,role,emailAddress"


def open_drive(*, write: bool):
    """Return ``(credentials, drive service)``. Write commands check scope first."""

    from gdocs import services
    from gdocs.auth import assert_write_scope, load_credentials

    creds, _storage = load_credentials()
    if write:
        assert_write_scope(creds)
    return creds, services.build("drive", "v3", creds)


def list_files(kind: str, *, name_contains: str | None = None, tag: str | None = None, starred: bool = False, limit: int | None = None) -> list[dict]:
    query = build_list_query(kind=kind, name_contains=name_contains, tag=tag, starred=starred)
    rows, _drive = _collect(query, limit)
    return rows


def find_files(kind: str, name_contains: str, *, tag: str | None = None, starred: bool = False, limit: int | None = None) -> list[dict]:
    return list_files(kind, name_contains=name_contains, tag=tag, starred=starred, limit=limit)


def search_files(kind: str, text: str, *, limit: int | None = None, snippets: int = 5) -> list[dict]:
    cap = _snippet_cap(snippets)
    query = build_list_query(kind=kind, full_text=text)
    rows, drive = _collect(query, limit)
    if cap:
        _fill_snippets(drive, rows, kind, text, cap)
    return rows


def resolve(drive, kind: str, target: str) -> dict:
    """Resolve an id, a URL, or a unique file name. Wrong type and ties fail closed."""

    from gdocs import services

    from gdocs.workspaces import alias_target, scope
    target = alias_target(target, kind)
    mime = KIND_MIME[kind]
    file_id = extract_id(target)
    if file_id:
        meta = services.execute(
            drive.files().get(fileId=file_id, fields=FILE_FIELDS, supportsAllDrives=True)
        )
        if meta.get("mimeType") != mime:
            raise GdocsError("file is the wrong type")
        return meta
    query = scope(build_list_query(kind=kind, name_equals=target))
    response = services.execute(
        drive.files().list(
            q=query,
            pageSize=2,
            fields=LIST_FIELDS,
            corpora="allDrives",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
    )
    files = response.get("files") or []
    if not files:
        raise GdocsError("file was not found")
    if len(files) > 1 or response.get("nextPageToken"):
        raise GdocsError("file name matches more than one file")
    return files[0]


def tag_list(kind: str, target: str) -> dict:
    _creds, drive = open_drive(write=False)
    meta = resolve(drive, kind, target)
    row = file_row(meta)
    return {"id": row["id"], "tags": row["tags"]}


def tag_add(kind: str, target: str, tags: list[str]) -> dict:
    return _tag_change(kind, target, add=tuple(tags), remove=())


def tag_remove(kind: str, target: str, tags: list[str]) -> dict:
    return _tag_change(kind, target, add=(), remove=tuple(tags))


def share(kind: str, target: str, who: str | None, role: str | None, yes: bool):
    """List, revoke, or create a permission. ``anyone`` is planned before a client exists."""

    if who in (None, ""):
        raise GdocsError("who must be user:email, group:email, domain:name, anyone, list, or revoke")
    if who == "list":
        return _share_list(kind, target)
    if who == "revoke":
        return _share_revoke(kind, target, role or "")
    body = plan_share(who, role or "", yes)
    return _share_create(kind, target, body)


def export_file(kind: str, target: str, fmt: str, dest: str, force: bool) -> dict:
    mime = export_mime(kind, fmt)
    path = Path(dest)
    prepare_output(path, force)
    _creds, drive = open_drive(write=False)
    meta = resolve(drive, kind, target)

    def writer(handle) -> None:
        _download_export(drive, meta["id"], mime, handle)

    atomic_write(path, writer)
    return {"id": meta["id"], "path": str(path), "format": fmt}


def import_file(kind: str, path: str, *, name: str | None = None) -> dict:
    """Upload a file and convert it to a Google editor file."""

    from gdocs import services

    source = Path(path)
    suffix = source.suffix.lower().lstrip(".")
    source_mime, target_mime = import_types(kind, suffix)
    title = _import_name(name, source)
    staged = stage_regular_file(source, MAX_IMPORT_BYTES)
    try:
        _creds, drive = open_drive(write=True)
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(staged, mimetype=source_mime, resumable=False)
        created = services.execute(
            drive.files().create(
                body={"name": title, "mimeType": target_mime},
                media_body=media,
                fields=FILE_FIELDS,
                supportsAllDrives=True,
            )
        )
        return file_row(created)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


def _collect(query: str, limit: int | None):
    from gdocs import services

    from gdocs.workspaces import scope
    query = scope(query)
    cap = list_limit(limit)
    _creds, drive = open_drive(write=False)
    rows: list[dict] = []
    token = None
    while len(rows) < cap:
        page_size = min(100, cap - len(rows))
        response = services.execute(
            drive.files().list(
                q=query,
                pageSize=page_size,
                pageToken=token,
                orderBy="modifiedTime desc",
                fields=LIST_FIELDS,
                corpora="allDrives",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
        )
        for meta in response.get("files") or []:
            rows.append(file_row(meta))
            if len(rows) >= cap:
                break
        token = response.get("nextPageToken")
        if not token:
            break
    return rows, drive


def _snippet_cap(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 20:
        raise GdocsError("snippets must be between 0 and 20")
    return value


def _fill_snippets(drive, rows: list[dict], kind: str, query: str, cap: int) -> None:
    mime = "text/csv" if kind == "sheet" else "text/plain"
    for index, row in enumerate(rows):
        if index >= cap:
            row["snippet"] = ""
            continue
        try:
            text = _export_text(drive, row.get("id"), mime)
            row["snippet"] = snippet_around(text, query)
        except Exception:
            row["snippet"] = ""


def _export_text(drive, file_id: str | None, mime: str) -> str:
    if not file_id:
        raise GdocsError("file was not found")
    from io import BytesIO

    buffer = BytesIO()
    _download_export(drive, file_id, mime, buffer, limit=_SNIPPET_BYTES)
    return buffer.getvalue()[:_SNIPPET_BYTES].decode("utf-8", "replace")


def _download_export(drive, file_id: str, mime: str, handle, limit: int = MAX_EXPORT_BYTES) -> None:
    from gdocs import services
    from googleapiclient.http import MediaIoBaseDownload

    request = drive.files().export_media(fileId=file_id, mimeType=mime)
    downloader = MediaIoBaseDownload(handle, request, chunksize=1024 * 1024)
    done = False
    while not done:
        _status, done = services.guard(downloader.next_chunk)
        if handle.tell() > limit:
            raise GdocsError("export exceeds the size limit")


def _tag_change(kind: str, target: str, *, add: tuple[str, ...], remove: tuple[str, ...]) -> dict:
    from gdocs import services

    for tag in (*add, *remove):
        check_tag(tag)
    if not add and not remove:
        raise GdocsError("missing tag")
    _creds, drive = open_drive(write=True)
    meta = resolve(drive, kind, target)
    props, changed = merge_tag_map(meta.get("appProperties"), add=add, remove=remove)
    if not changed:
        raise GdocsError("edit changed nothing")
    updated = services.execute(
        drive.files().update(
            fileId=meta["id"],
            body={"appProperties": props},
            fields=FILE_FIELDS,
            supportsAllDrives=True,
        )
    )
    return file_row(updated)


def _share_list(kind: str, target: str) -> list:
    from gdocs import services

    _creds, drive = open_drive(write=False)
    meta = resolve(drive, kind, target)
    response = services.execute(
        drive.permissions().list(
            fileId=meta["id"],
            fields=f"permissions({_SHARE_FIELDS})",
            supportsAllDrives=True,
        )
    )
    return response.get("permissions") or []


def _share_revoke(kind: str, target: str, permission_id: str) -> dict:
    from gdocs import services

    if not _PERM_ID.fullmatch(permission_id or ""):
        raise GdocsError("permission id is invalid")
    _creds, drive = open_drive(write=True)
    meta = resolve(drive, kind, target)
    services.execute(
        drive.permissions().delete(
            fileId=meta["id"],
            permissionId=permission_id,
            supportsAllDrives=True,
        )
    )
    return {"id": meta["id"], "revoked": permission_id}


def _share_create(kind: str, target: str, body: dict) -> dict:
    from gdocs import services

    _creds, drive = open_drive(write=True)
    meta = resolve(drive, kind, target)
    notify = body.get("type") in {"user", "group"}
    return services.execute(
        drive.permissions().create(
            fileId=meta["id"],
            body=body,
            sendNotificationEmail=notify,
            fields=_SHARE_FIELDS,
            supportsAllDrives=True,
        )
    )


def _import_name(name: str | None, source: Path) -> str:
    title = name if name else source.stem
    if not isinstance(title, str) or not title.strip():
        raise GdocsError("import name is missing")
    if len(title) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in title):
        raise GdocsError("import name is invalid")
    return title


def check_title(name) -> str:
    if not isinstance(name, str) or not name.strip():
        raise GdocsError("name is missing")
    if len(name) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise GdocsError("name is invalid")
    return name


def create_file(kind: str, name: str) -> dict:
    """Create an empty Google editor file. The title is checked before a client is built."""

    title = check_title(name)
    from gdocs import services

    _creds, drive = open_drive(write=True)
    created = services.execute(
        drive.files().create(
            body={"name": title, "mimeType": KIND_MIME[kind]},
            fields=FILE_FIELDS,
            supportsAllDrives=True,
        )
    )
    row = file_row(created)
    if not _ID.fullmatch(row.get("id") or ""):
        raise GdocsError("created file id is invalid")
    return row


def trash_file(file_id: str) -> None:
    if not _ID.fullmatch(file_id or ""):
        raise GdocsError("file id is invalid")
    from gdocs import services

    _creds, drive = open_drive(write=True)
    services.execute(
        drive.files().update(
            fileId=file_id,
            body={"trashed": True},
            supportsAllDrives=True,
        )
    )


def abandon(file_id: str, exc: BaseException) -> NoReturn:
    try:
        trash_file(file_id)
    except Exception:
        raise GdocsError(f"{exc}; leftover file {file_id}") from None
    raise exc from None
