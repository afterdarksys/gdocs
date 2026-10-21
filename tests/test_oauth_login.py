import json
from unittest.mock import Mock

import pytest

from gdocs import auth
from gdocs.cli import main


@pytest.mark.parametrize("readonly", [False, True])
def test_oauth_login_stores_and_refreshes_credentials(tmp_path, monkeypatch, capsys, readonly):
    scope = auth.SCOPE_READONLY if readonly else auth.SCOPE_DRIVE
    client = tmp_path / "client.json"
    client.write_text(json.dumps({"installed": {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": auth.TOKEN_URI,
        "redirect_uris": ["http://localhost"],
    }}))
    info = {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "refresh_token": "refresh-secret",
        "token": "expired-access",
        "token_uri": auth.TOKEN_URI,
        "scopes": [scope],
        "expiry": "2000-01-01T00:00:00Z",
    }
    flow = Mock()
    flow.run_local_server.return_value.to_json.return_value = json.dumps(info)
    factory = Mock(return_value=flow)
    monkeypatch.setattr("google_auth_oauthlib.flow.InstalledAppFlow.from_client_config", factory)
    argv = ["login", "--client", str(client), "--output", "json"]
    if readonly:
        argv.append("--readonly")
    assert main(argv) == 0
    assert factory.call_args.kwargs["scopes"] == [scope]
    options = flow.run_local_server.call_args.kwargs
    assert options["bind_addr"] == "127.0.0.1"
    assert options["open_browser"] is True
    assert options["access_type"] == "offline"
    assert options["prompt"] == "consent"
    assert auth.load_stored()[0]["refresh_token"] == "refresh-secret"
    assert "secret" not in capsys.readouterr().out

    def refresh(credentials):
        from datetime import datetime, timedelta, timezone

        assert credentials.refresh_token == "refresh-secret"
        credentials.token = "new-access"
        credentials.expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)

    monkeypatch.setattr(auth, "_refresh", refresh)
    credentials, storage = auth.load_credentials()
    assert credentials.valid
    assert credentials.token == "new-access"
    assert storage == "file"
    assert auth.load_stored()[0]["token"] == "new-access"
