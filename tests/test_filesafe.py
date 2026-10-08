import os
import stat
from pathlib import Path

import pytest

from gdocs.errors import GdocsError
from gdocs.filesafe import atomic_write, check_import_file, prepare_output, stage_regular_file


def test_prepare_output_refuses_symlinks_and_clobber(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(GdocsError, match="symlink"):
        prepare_output(link / "out.txt", False)

    target = tmp_path / "target.txt"
    target.write_text("x")
    dest = tmp_path / "dest.txt"
    dest.symlink_to(target)
    with pytest.raises(GdocsError, match="symlink"):
        prepare_output(dest, True)

    existing = tmp_path / "exists.txt"
    existing.write_text("kept")
    with pytest.raises(GdocsError, match="already exists"):
        prepare_output(existing, False)


def test_atomic_write_mode(tmp_path):
    dest = tmp_path / "out.bin"
    atomic_write(dest, lambda handle: handle.write(b"abc"))
    assert dest.read_bytes() == b"abc"
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600


def test_import_checks_and_stage(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    with pytest.raises(GdocsError, match="empty"):
        check_import_file(empty)
    with pytest.raises(GdocsError, match="was not found"):
        check_import_file(tmp_path / "missing.csv")

    real = tmp_path / "real.csv"
    real.write_text("a,b\n")
    linked = tmp_path / "linked.csv"
    linked.symlink_to(real)
    with pytest.raises(GdocsError, match="symlink"):
        check_import_file(linked)

    staged = stage_regular_file(real, 1000)
    try:
        assert Path(staged).read_text() == "a,b\n"
        assert stat.S_IMODE(os.stat(staged).st_mode) == 0o600
    finally:
        os.unlink(staged)
