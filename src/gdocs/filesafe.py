"""Local file checks for token files, imports, and exports."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from gdocs.errors import GdocsError

MAX_IMPORT_BYTES = 50 * 1024 * 1024
MAX_EXPORT_BYTES = 200 * 1024 * 1024


def read_bounded(path: Path, limit: int, *, follow_symlink: bool = False) -> bytes:
    """Read at most ``limit`` bytes. Reject a larger file."""

    if not follow_symlink and os.path.islink(path):
        raise GdocsError("refusing to read a symlink")
    try:
        fd = os.open(path, os.O_RDONLY | (0 if follow_symlink else os.O_NOFOLLOW))
    except OSError:
        raise GdocsError("refusing to read the file") from None
    try:
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining > 0:
            block = os.read(fd, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) > limit:
        raise GdocsError("input exceeds the size limit")
    return data


def read_text_input(path: str, limit: int) -> str:
    if path == "-":
        data = sys_read_stdin(limit)
    else:
        data = read_bounded(Path(path), limit)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise GdocsError("input is not UTF-8") from None


def sys_read_stdin(limit: int) -> bytes:
    import sys

    data = sys.stdin.buffer.read(limit + 1)
    if data is None:
        data = b""
    if len(data) > limit:
        raise GdocsError("input exceeds the size limit")
    return data


def check_import_file(path: Path) -> int:
    if os.path.islink(path):
        raise GdocsError("refusing to import a symlink")
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise GdocsError("import file was not found") from None
    if not stat.S_ISREG(st.st_mode):
        raise GdocsError("import path is not a regular file")
    if st.st_size <= 0:
        raise GdocsError("import file is empty")
    if st.st_size > MAX_IMPORT_BYTES:
        raise GdocsError("import file exceeds 50MB")
    return st.st_size


def stage_regular_file(path: Path, limit: int) -> str:
    """Copy a regular file to a private temp file and return that path.

    The caller deletes the temp file. ``O_NOFOLLOW`` refuses a symlink swap
    between the size check and the read.
    """

    check_import_file(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise GdocsError("refusing to import the file") from None
    handle = tempfile.NamedTemporaryFile(prefix="gdocs-import-", delete=False)
    total = 0
    try:
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > limit:
                raise GdocsError("import file exceeds 50MB")
            handle.write(block)
    except Exception:
        handle.close()
        os.unlink(handle.name)
        raise
    finally:
        os.close(fd)
    handle.close()
    if total <= 0:
        os.unlink(handle.name)
        raise GdocsError("import file is empty")
    os.chmod(handle.name, 0o600)
    return handle.name


def prepare_output(path: Path, force: bool) -> None:
    if os.path.islink(path):
        raise GdocsError("refusing to write through a symlink")
    if path.exists() and not force:
        raise GdocsError(f"{path} already exists; pass --force")
    parent = path.parent
    if os.path.islink(parent):
        raise GdocsError("refusing to write through a symlink")
    if parent.exists() and not parent.is_dir():
        raise GdocsError("output directory is missing")
    parent.mkdir(parents=True, exist_ok=True)


def atomic_write(path: Path, writer) -> None:
    """Let ``writer(fileobj)`` fill a temp file in the destination directory, then replace."""

    parent = path.parent
    fd, tmp_name = tempfile.mkstemp(dir=parent, prefix=".gdocs-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        if os.path.islink(path):
            raise GdocsError("refusing to write through a symlink")
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    os.chmod(path, 0o600)
