import json

import pytest

from gdocs import auth
from gdocs.cli import main


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "client file.json"
    path.write_text(json.dumps({"installed": {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": auth.TOKEN_URI,
        "redirect_uris": ["http://localhost"],
    }}))
    return path


@pytest.fixture
def wizard(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    calls = []
    monkeypatch.setattr(auth, "login", lambda *args: calls.append(args) or ("keyring", []))

    def answers(*values):
        iterator = iter(values)
        monkeypatch.setattr("builtins.input", lambda: next(iterator))

    return calls, answers


def test_full_guide_and_readwrite(client, wizard, capsys):
    calls, answers = wizard
    answers("n", "", "", "", "", str(client), "", "")
    assert main(["setup"]) == 0
    assert calls == [(str(client), False)]
    err = capsys.readouterr().err
    assert "Google Slides API" in err
    assert "Setup complete" in err
    assert "client-secret" not in err


def test_retries_bad_path_and_invalid_answer(client, wizard, capsys):
    calls, answers = wizard
    answers("maybe", "yes", "/missing/client.json", f'"{client}"', "yes", "yes")
    assert main(["setup"]) == 0
    assert calls == [(str(client), True)]
    assert "Cannot use client JSON" in capsys.readouterr().err


def test_flags_expand_home(client, wizard, monkeypatch):
    calls, answers = wizard
    monkeypatch.setenv("HOME", str(client.parent))
    answers("")
    assert main(["setup", "--client", "~/client file.json", "--readonly"]) == 0
    assert calls == [(str(client), True)]


def test_cancel_does_not_login(client, wizard, capsys):
    calls, answers = wizard
    answers("n")
    assert main(["setup", "--client", str(client), "--readonly"]) == 1
    assert not calls
    assert "Setup complete" not in capsys.readouterr().err


def test_invalid_explicit_client_does_not_login(wizard):
    calls, _ = wizard
    assert main(["setup", "--client", "/missing/client.json"]) == 1
    assert not calls


def test_reject_web_client(client, wizard, capsys):
    calls, _ = wizard
    data = json.loads(client.read_text())
    client.write_text(json.dumps({"web": data["installed"]}))
    assert main(["setup", "--client", str(client)]) == 1
    assert not calls
    assert "Desktop app" in capsys.readouterr().err


@pytest.mark.parametrize("exception,code", [(EOFError, 1), (KeyboardInterrupt, 130)])
def test_interrupted_input(wizard, monkeypatch, exception, code):
    calls, _ = wizard

    def interrupt():
        raise exception

    monkeypatch.setattr("builtins.input", interrupt)
    assert main(["setup"]) == code
    assert not calls


def test_noninteractive(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["setup"]) == 1
    assert "gdocs login --client" in capsys.readouterr().err
    assert main(["setup", "--help"]) == 0


def test_login_failure_is_not_success(client, wizard, monkeypatch, capsys):
    _, answers = wizard
    answers("")

    def fail(*args):
        raise auth.GdocsError("login did not grant the Drive scope")

    monkeypatch.setattr(auth, "login", fail)
    assert main(["setup", "--client", str(client), "--readonly"]) == 1
    assert "Setup complete" not in capsys.readouterr().err
