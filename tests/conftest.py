import pytest


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("GDOCS_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("GDOCS_DISABLE_KEYRING", "1")
    monkeypatch.delenv("GDOCS_DEBUG", raising=False)
