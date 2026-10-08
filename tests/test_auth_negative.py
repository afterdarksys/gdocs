import json
import os
import stat
from pathlib import Path

import pytest

from gdocs.auth import (
    SCOPE_DRIVE,
    TOKEN_URI,
    load_client_secrets,
    logout,
    read_token_file,
    status_view,
    validate_client_secrets,
    validate_token_info,
    write_token_file,
)
from gdocs.cli import main
from gdocs.errors import GdocsError, report_exception
from gdocs.redact import redact


def _info(**overrides):
    base = {
        "refresh_token": "refresh-token",
        "token_uri": TOKEN_URI,
        "client_id": "client-id",
        "client_secret": "client-secret",
        "scopes": [SCOPE_DRIVE],
    }
    base.update(overrides)
    return base


def _client(**overrides):
    block = {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": TOKEN_URI,
        "redirect_uris": ["http://localhost"],
    }
    block.update(overrides)
    return {"installed": block}


def test_scope_and_secret_rejection():
    gmail = "https://www.googleapis.com/auth/gmail.readonly"
    with pytest.raises(GdocsError, match="token scopes are not the Drive scope") as caught:
        validate_token_info(_info(scopes=[gmail]))
    assert gmail not in str(caught.value)

    with pytest.raises(GdocsError, match="token scopes are missing"):
        validate_token_info(_info(scopes=[]))
    with pytest.raises(GdocsError, match="token scopes are invalid"):
        validate_token_info(_info(scopes=[SCOPE_DRIVE, SCOPE_DRIVE]))
    with pytest.raises(GdocsError, match="token scopes are invalid"):
        validate_token_info(_info(scopes=[SCOPE_DRIVE, SCOPE_DRIVE, SCOPE_DRIVE]))
    with pytest.raises(GdocsError, match="token endpoint is not Google's"):
        validate_token_info(_info(token_uri="https://evil.example/token"))
    with pytest.raises(GdocsError, match="too long"):
        validate_token_info(_info(refresh_token="r" * 4097))
    with pytest.raises(GdocsError, match="refresh token is invalid"):
        validate_token_info(_info(refresh_token="   "))
    with pytest.raises(GdocsError, match="refresh token is missing"):
        validate_token_info(_info(refresh_token=""))


def test_token_file_modes(tmp_path):
    path = tmp_path / "token.json"
    path.write_text("{}\n")
    os.chmod(path, 0o600)
    assert read_token_file(path) == b"{}\n"

    os.chmod(path, 0o640)
    with pytest.raises(GdocsError, match="group or world accessible"):
        read_token_file(path)
    os.chmod(path, 0o644)
    with pytest.raises(GdocsError, match="group or world accessible"):
        read_token_file(path)

    path.unlink()
    target = tmp_path / "real.json"
    target.write_text("{}")
    path.symlink_to(target)
    with pytest.raises(GdocsError, match="symlink"):
        read_token_file(path)


def test_client_secret_file(tmp_path):
    path = tmp_path / "client.json"
    path.write_text(json.dumps(_client()))
    os.chmod(path, 0o644)
    loaded = load_client_secrets(str(path))
    assert loaded["installed"]["client_id"] == "client-id"

    os.chmod(path, 0o666)
    with pytest.raises(GdocsError, match="world writable"):
        load_client_secrets(str(path))

    path.unlink()
    real = tmp_path / "real.json"
    real.write_text(json.dumps(_client()))
    path.symlink_to(real)
    with pytest.raises(GdocsError, match="symlink"):
        load_client_secrets(str(path))

    missing = tmp_path / "missing.json"
    with pytest.raises(GdocsError, match="client secret file was not found") as caught:
        load_client_secrets(str(missing))
    assert "not logged in" not in str(caught.value)


def test_client_secret_endpoints():
    with pytest.raises(GdocsError, match="client auth endpoint"):
        validate_client_secrets(_client(auth_uri="https://evil.example/auth"))
    with pytest.raises(GdocsError, match="client token endpoint"):
        validate_client_secrets(_client(token_uri="https://evil.example/token"))
    for uri in (
        "http://127.0.0.1.evil.com/callback",
        "urn:ietf:wg:oauth:2.0:oob",
        "http://user:pass@127.0.0.1/",
        "http://localhost.evil.com/callback",
    ):
        with pytest.raises(GdocsError, match="localhost"):
            validate_client_secrets(_client(redirect_uris=[uri]))
    validate_client_secrets(_client(redirect_uris=["http://127.0.0.1:8080/"]))
    validate_client_secrets(_client(redirect_uris=["http://localhost"]))


def test_status_view_keys_only():
    view = status_view(email="ada@example.com", scopes=[SCOPE_DRIVE], storage="file", expiry=None)
    assert set(view) == {"email", "scopes", "storage", "expiry"}


def test_redact_tokens(capsys):
    assert redact("prefix ya29.SECRETTOKEN suffix") == "prefix [redacted] suffix"
    assert "REFRESHSECRET" not in redact("1//REFRESHSECRET")
    code = report_exception(GdocsError("failed ya29.SECRETTOKEN"))
    err = capsys.readouterr().err
    assert code == 1
    assert "[redacted]" in err
    assert "SECRETTOKEN" not in err


def test_write_token_file_mode(tmp_path):
    path = tmp_path / "cfg" / "token.json"
    write_token_file(path, "{}")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_access_token_alias_and_unknown_keys():
    cleaned = validate_token_info(_info(access_token="access-value"))
    assert cleaned["token"] == "access-value"
    assert "access_token" not in cleaned

    both = _info(token="secret-token-a")
    both["access_token"] = "secret-token-b"
    with pytest.raises(GdocsError, match="token file is invalid") as caught:
        validate_token_info(both)
    text = str(caught.value)
    assert "secret-token-a" not in text
    assert "secret-token-b" not in text

    cleaned = validate_token_info(_info(extra="drop-me"))
    assert "extra" not in cleaned


def test_logout_without_token():
    with pytest.raises(GdocsError, match="not logged in"):
        logout()
    assert main(["logout"]) == 1


def test_status_does_not_print_secrets(capsys, monkeypatch):
    class Creds:
        token = "ya29.LEAKEDTOKEN"
        refresh_token = "1//LEAKEDREFRESH"
        client_secret = "client-secret-leak"
        scopes = [SCOPE_DRIVE]
        valid = True
        expired = False
        expiry = None

    class Request:
        def execute(self):
            return {"user": {"emailAddress": "ada@example.com"}}

    class About:
        def get(self, fields):
            assert fields == "user(emailAddress)"
            return Request()

    class Drive:
        def about(self):
            return About()

    monkeypatch.setattr("gdocs.auth.load_credentials", lambda: (Creds(), "file"))
    monkeypatch.setattr("gdocs.services.build", lambda api, version, creds: Drive())

    assert main(["status", "--output", "json"]) == 0
    out = capsys.readouterr().out
    assert "ada@example.com" in out
    assert "LEAKED" not in out
    assert "client-secret-leak" not in out
    assert "ya29" not in out
