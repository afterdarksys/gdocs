import pytest
from unittest.mock import Mock
from gdocs import profiles, auth, preferences
from gdocs.errors import GdocsError

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('GDOCS_CONFIG_DIR', str(tmp_path))
    monkeypatch.delenv('GDOCS_PROFILE', raising=False)
    monkeypatch.delenv('GDOCS_WORKSPACE', raising=False)

def test_isolation_and_legacy_paths(tmp_path, monkeypatch):
    assert auth.token_path() == tmp_path / 'token.json'
    assert profiles.keyring_account() == 'default'
    preferences.save({'output': 'plain'})
    profiles.create('work', 'engineer@example.com'); profiles.use('work')
    assert auth.token_path() == tmp_path / 'profiles/work/token.json'
    assert preferences.load() == {}
    work_account = profiles.keyring_account()
    profiles.create('personal'); profiles.use('personal')
    assert profiles.keyring_account() != work_account
    monkeypatch.setenv('GDOCS_PROFILE', 'default')
    assert preferences.load()['output'] == 'plain'
    monkeypatch.setenv('GDOCS_PROFILE', '../outside')
    with pytest.raises(GdocsError): auth.token_path()

def test_write_identity_check(capsys):
    profiles.create('work', 'engineer@example.com'); profiles.use('work')
    drive = Mock()
    drive.about.return_value.get.return_value.execute.return_value = {'user': {'emailAddress': 'wrong@example.com'}}
    with pytest.raises(GdocsError, match='differs'): profiles.write_context(drive)
    drive.about.return_value.get.return_value.execute.return_value = {'user': {'emailAddress': 'engineer@example.com'}}
    profiles.write_context(drive)
    assert 'engineer@example.com' in capsys.readouterr().err

def test_logout_is_profile_specific(monkeypatch):
    import keyring
    monkeypatch.delenv("GDOCS_DISABLE_KEYRING", raising=False)
    profiles.create('work'); profiles.use('work')
    delete = Mock(); monkeypatch.setattr(keyring, 'delete_password', delete)
    monkeypatch.setattr(keyring, 'get_password', lambda *a: 'present')
    auth.logout()
    assert delete.call_args.args == ('gdocs', profiles.keyring_account())
