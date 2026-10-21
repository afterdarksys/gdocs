import subprocess
from pathlib import Path


LAUNCHER = Path(__file__).resolve().parents[1] / "bin" / "gdocs"


def test_launcher_outside_checkout_via_symlink(tmp_path):
    link = tmp_path / "gdocs link"
    link.symlink_to(LAUNCHER)
    result = subprocess.run(
        [str(link), "login", "--help"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--client" in result.stdout
    assert "--readonly" in result.stdout


def test_launcher_preserves_relative_client_path(tmp_path):
    (tmp_path / "client file.json").write_text("{}")
    result = subprocess.run(
        [str(LAUNCHER), "login", "--client", "client file.json"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "needs an installed or web client" in result.stderr
