"""OAuth token storage and validation.

Threats: a stolen refresh token from a loose token file or a symlink swap,
a swapped token_uri that would send the refresh token somewhere other than
Google, unexpected scopes, an oversized blob, and a world-accessible token
file. Missing credentials and a failed refresh fail closed. Does not protect
a stolen OS keychain, a malicious OAuth client the operator configures, or
a compromised Google account.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from gdocs.errors import GdocsError

SCOPE_DRIVE = "https://www.googleapis.com/auth/drive"
SCOPE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
ALLOWED_SCOPES = frozenset({SCOPE_DRIVE, SCOPE_READONLY})
TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_URIS = frozenset(
    {
        "https://accounts.google.com/o/oauth2/auth",
        "https://accounts.google.com/o/oauth2/v2/auth",
    }
)
CERT_URL = "https://www.googleapis.com/oauth2/v1/certs"
KEYRING_SERVICE = "gdocs"
KEYRING_ACCOUNT = "default"
MAX_BLOB = 65536
MAX_REFRESH = 4096
MAX_ACCESS = 8192
MAX_CLIENT_FIELD = 2048
_TOKEN_KEYS = (
    "token",
    "refresh_token",
    "token_uri",
    "client_id",
    "client_secret",
    "scopes",
    "expiry",
    "universe_domain",
)


def config_dir() -> Path:
    override = os.environ.get("GDOCS_CONFIG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".config" / "gdocs"


def token_path() -> Path:
    return config_dir() / "token.json"


def validate_token_info(info: dict) -> dict:
    """Return a cleaned authorized-user dict, or raise GdocsError.

    Unknown keys are dropped so a library extra field cannot change the
    token endpoint or the scopes. The error text never includes the secret.
    """

    if not isinstance(info, dict):
        raise GdocsError("token file is invalid")
    refresh = _bounded_secret(info.get("refresh_token"), "refresh token", MAX_REFRESH)
    client_id = _bounded_secret(info.get("client_id"), "client id", MAX_CLIENT_FIELD)
    client_secret = _bounded_secret(info.get("client_secret"), "client secret", MAX_CLIENT_FIELD)
    token_uri = info.get("token_uri")
    if token_uri != TOKEN_URI:
        raise GdocsError("token endpoint is not Google's")
    scopes = info.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        raise GdocsError("token scopes are missing")
    if len(scopes) > 2 or len(set(scopes)) != len(scopes):
        raise GdocsError("token scopes are invalid")
    for scope in scopes:
        if scope not in ALLOWED_SCOPES:
            raise GdocsError("token scopes are not the Drive scope")
    cleaned: dict = {
        "refresh_token": refresh,
        "token_uri": TOKEN_URI,
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": list(scopes),
    }
    token_value = info.get("token")
    alias = info.get("access_token")
    token_set = isinstance(token_value, str) and token_value != ""
    alias_set = isinstance(alias, str) and alias != ""
    if token_set and alias_set:
        raise GdocsError("token file is invalid")
    if alias_set:
        token_value = alias
        token_set = True
    if token_set:
        cleaned["token"] = _bounded_secret(token_value, "access token", MAX_ACCESS)
    if "expiry" in info and info.get("expiry") not in (None, ""):
        expiry = info.get("expiry")
        if not isinstance(expiry, str) or len(expiry) > 64:
            raise GdocsError("token expiry is invalid")
        if any(ord(ch) < 32 for ch in expiry):
            raise GdocsError("token expiry is invalid")
        cleaned["expiry"] = expiry
    if "universe_domain" in info and info.get("universe_domain") not in (None, ""):
        domain = info.get("universe_domain")
        if domain != "googleapis.com":
            raise GdocsError("token universe is invalid")
        cleaned["universe_domain"] = domain
    encoded = json.dumps(cleaned, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(encoded) > MAX_BLOB:
        raise GdocsError("token blob is too large")
    return cleaned


def validate_client_secrets(data: dict) -> dict:
    if not isinstance(data, dict):
        raise GdocsError("client secret file is invalid")
    if "installed" in data:
        kind = "installed"
    elif "web" in data:
        kind = "web"
    else:
        raise GdocsError("client secret file needs an installed or web client")
    block = data[kind]
    if not isinstance(block, dict):
        raise GdocsError("client secret file is invalid")
    client_id = _bounded_secret(block.get("client_id"), "client id", MAX_CLIENT_FIELD)
    client_secret = _bounded_secret(block.get("client_secret"), "client secret", MAX_CLIENT_FIELD)
    if block.get("auth_uri") not in AUTH_URIS:
        raise GdocsError("client auth endpoint is not Google's")
    if block.get("token_uri") != TOKEN_URI:
        raise GdocsError("client token endpoint is not Google's")
    redirects = block.get("redirect_uris")
    if not isinstance(redirects, list) or not redirects:
        raise GdocsError("client redirect URIs are missing")
    if len(redirects) > 10:
        raise GdocsError("client redirect URIs are invalid")
    for uri in redirects:
        if not isinstance(uri, str) or not _loopback_uri(uri):
            raise GdocsError("client redirect URI must be localhost")
    cleaned = {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": block["auth_uri"],
        "token_uri": TOKEN_URI,
        "redirect_uris": list(redirects),
    }
    origins = block.get("javascript_origins")
    if origins is not None:
        if not isinstance(origins, list) or len(origins) > 10:
            raise GdocsError("client javascript origins are invalid")
        for origin in origins:
            if not isinstance(origin, str) or not _loopback_uri(origin):
                raise GdocsError("client javascript origin must be localhost")
        cleaned["javascript_origins"] = list(origins)
    project = block.get("project_id")
    if project not in (None, ""):
        if not isinstance(project, str) or len(project) > 200:
            raise GdocsError("client project id is invalid")
        cleaned["project_id"] = project
    certs = block.get("auth_provider_x509_cert_url")
    if certs not in (None, ""):
        if certs != CERT_URL:
            raise GdocsError("client certificate URL is not Google's")
        cleaned["auth_provider_x509_cert_url"] = CERT_URL
    return {kind: cleaned}


def status_view(*, email: str, scopes: list[str], storage: str, expiry: str | None) -> dict:
    """Fields safe to print. Tokens and the client secret are not accepted."""

    view = {
        "email": email,
        "scopes": list(scopes),
        "storage": storage,
        "expiry": expiry,
    }
    if set(view) != {"email", "scopes", "storage", "expiry"}:
        raise GdocsError("status view refused")
    return view


def assert_write_scope(creds) -> None:
    scopes = list(getattr(creds, "scopes", None) or [])
    if SCOPE_DRIVE not in scopes:
        raise GdocsError("this command needs a read-write login: gdocs login --client CLIENT.json")
    for scope in scopes:
        if scope not in ALLOWED_SCOPES:
            raise GdocsError("stored scopes are not the Drive scope")


def load_client_secrets(path: str) -> dict:
    file_path = Path(path)
    raw = _read_client_bytes(file_path)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise GdocsError("client secret file is not valid JSON") from None
    return validate_client_secrets(data)


def login(client_path: str, readonly: bool) -> tuple[str, list[str]]:
    secrets = load_client_secrets(client_path)
    scopes = [SCOPE_READONLY if readonly else SCOPE_DRIVE]
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(secrets, scopes=scopes)
    creds = flow.run_local_server(
        bind_addr="127.0.0.1",
        port=0,
        prompt="consent",
        access_type="offline",
        open_browser=True,
    )
    info = json.loads(creds.to_json())
    if not info.get("scopes"):
        info["scopes"] = list(scopes)
    cleaned = validate_token_info(info)
    granted = set(cleaned["scopes"])
    if readonly:
        if granted != {SCOPE_READONLY}:
            raise GdocsError("readonly login granted unexpected scopes")
    elif SCOPE_DRIVE not in granted:
        raise GdocsError("login did not grant the Drive scope")
    storage = save_token_info(cleaned)
    return storage, cleaned["scopes"]


def logout() -> None:
    removed = False
    if os.environ.get("GDOCS_DISABLE_KEYRING") != "1":
        existing = _keyring_get()
        if existing:
            _keyring_delete()
            removed = True
    path = token_path()
    if os.path.lexists(path):
        if os.path.islink(path) or os.path.isfile(path):
            os.remove(path)
            removed = True
        else:
            raise GdocsError("token path is not a file")
    if not removed:
        raise GdocsError("not logged in")


def load_credentials():
    """Return ``(credentials, storage)``. Refreshes and stores when needed."""

    info, storage = load_stored()
    creds = _credentials_from_info(info)
    if not getattr(creds, "refresh_token", None):
        raise GdocsError("not logged in")
    token = getattr(creds, "token", None)
    if not token or getattr(creds, "expired", False) or not getattr(creds, "valid", False):
        _refresh(creds)
        refreshed = json.loads(creds.to_json())
        for key in ("refresh_token", "client_id", "client_secret", "token_uri", "scopes"):
            if not refreshed.get(key):
                refreshed[key] = info.get(key)
        cleaned = validate_token_info(refreshed)
        storage = save_token_info(cleaned)
        creds = _credentials_from_info(cleaned)
    assert_known_scopes(creds)
    return creds, storage


def assert_known_scopes(creds) -> None:
    scopes = list(getattr(creds, "scopes", None) or [])
    if not scopes:
        raise GdocsError("token scopes are missing")
    for scope in scopes:
        if scope not in ALLOWED_SCOPES:
            raise GdocsError("stored scopes are not the Drive scope")


def load_stored() -> tuple[dict, str]:
    if os.environ.get("GDOCS_DISABLE_KEYRING") != "1":
        raw = _keyring_get()
        if raw:
            if len(raw.encode("utf-8")) > MAX_BLOB:
                raise GdocsError("token blob is too large")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                raise GdocsError("token file is not valid JSON") from None
            return validate_token_info(parsed), "keyring"
    path = token_path()
    if not os.path.lexists(path):
        raise GdocsError("not logged in")
    raw_bytes = read_token_file(path)
    try:
        parsed = json.loads(raw_bytes)
    except json.JSONDecodeError:
        raise GdocsError("token file is not valid JSON") from None
    return validate_token_info(parsed), "file"


def save_token_info(info: dict) -> str:
    cleaned = validate_token_info(info)
    payload = json.dumps(cleaned, separators=(",", ":"), sort_keys=True)
    if len(payload.encode("utf-8")) > MAX_BLOB:
        raise GdocsError("token blob is too large")
    if os.environ.get("GDOCS_DISABLE_KEYRING") == "1":
        write_token_file(token_path(), payload)
        return "file"
    try:
        _keyring_set(payload)
    except GdocsError:
        raise
    except Exception:
        write_token_file(token_path(), payload)
        return "file"
    path = token_path()
    if os.path.lexists(path):
        if os.path.islink(path) or os.path.isfile(path):
            os.remove(path)
    return "keyring"


def read_token_file(path: Path) -> bytes:
    return _read_mode_checked(path, max_bytes=MAX_BLOB, forbid_group_world=True, forbid_world_write=True)


def write_token_file(path: Path, payload: str) -> None:
    if os.path.lexists(path) and os.path.islink(path):
        raise GdocsError("token file is a symlink")
    parent = path.parent
    if os.path.islink(parent):
        raise GdocsError("config directory is a symlink")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.path.islink(parent) or not parent.is_dir():
        raise GdocsError("config directory is a symlink")
    os.chmod(parent, 0o700)
    data = payload.encode("utf-8")
    if len(data) > MAX_BLOB:
        raise GdocsError("token blob is too large")
    fd, tmp_name = tempfile.mkstemp(dir=parent, prefix=".token-", suffix=".tmp")
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp_name, 0o600)
    try:
        if os.path.islink(path):
            raise GdocsError("token file is a symlink")
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    os.chmod(path, 0o600)


def cmd_login(args) -> None:
    from gdocs.output import emit

    storage, scopes = login(args.client, args.readonly)
    emit({"storage": storage, "scopes": scopes}, args.output)


def cmd_logout(_args) -> None:
    logout()
    print("logged out")


def cmd_status(args) -> None:
    from gdocs.output import emit
    from gdocs.services import build, execute

    creds, storage = load_credentials()
    drive = build("drive", "v3", creds)
    about = execute(drive.about().get(fields="user(emailAddress)"))
    email = ((about.get("user") or {}).get("emailAddress")) or ""
    expiry = creds.expiry.isoformat() if getattr(creds, "expiry", None) else None
    emit(
        status_view(email=email, scopes=sorted(list(creds.scopes or [])), storage=storage, expiry=expiry),
        args.output,
    )


def _credentials_from_info(info: dict):
    from google.oauth2.credentials import Credentials

    return Credentials.from_authorized_user_info(info)


def _refresh(creds) -> None:
    from google.auth.transport.requests import Request as GoogleRequest

    class _PinnedRequest:
        def __init__(self) -> None:
            self._inner = GoogleRequest()

        def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kwargs):
            endpoint = url.split("?", 1)[0]
            if endpoint != TOKEN_URI:
                raise GdocsError("refusing token request to an unexpected endpoint")
            try:
                return self._inner(
                    url,
                    method=method,
                    body=body,
                    headers=headers,
                    timeout=60,
                    **kwargs,
                )
            except GdocsError:
                raise
            except Exception:
                raise GdocsError("token refresh failed") from None

    try:
        creds.refresh(_PinnedRequest())
    except GdocsError:
        raise
    except Exception:
        raise GdocsError("token refresh failed") from None


def _keyring_get() -> str | None:
    import keyring

    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except Exception:
        return None


def _keyring_set(payload: str) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, payload)


def _keyring_delete() -> None:
    import keyring

    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except Exception:
        raise GdocsError("could not delete the keychain token") from None


def _read_client_bytes(path: Path) -> bytes:
    return _read_mode_checked(
        path,
        max_bytes=MAX_BLOB,
        forbid_group_world=False,
        forbid_world_write=True,
        missing="client secret file was not found",
    )


def _read_mode_checked(
    path: Path,
    *,
    max_bytes: int,
    forbid_group_world: bool,
    forbid_world_write: bool,
    missing: str = "not logged in",
) -> bytes:
    if os.path.islink(path):
        raise GdocsError(f"{path.name} is a symlink")
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise GdocsError(missing) from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise GdocsError(f"{path.name} is not a regular file")
    if st.st_size > max_bytes:
        raise GdocsError(f"{path.name} is too large")
    mode = stat.S_IMODE(st.st_mode)
    if forbid_group_world and mode & 0o077:
        raise GdocsError(f"{path.name} is group or world accessible")
    if forbid_world_write and mode & 0o002:
        raise GdocsError(f"{path.name} is world writable")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise GdocsError(f"refusing to read {path.name}") from None
    try:
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            block = os.read(fd, remaining)
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) > max_bytes:
        raise GdocsError(f"{path.name} is too large")
    return data


def _bounded_secret(value, label: str, max_len: int) -> str:
    if not isinstance(value, str) or value == "":
        raise GdocsError(f"{label} is missing")
    if not value.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise GdocsError(f"{label} is invalid")
    if len(value) > max_len:
        raise GdocsError(f"{label} is too long")
    return value


def _loopback_uri(uri: str) -> bool:
    if len(uri) > 500:
        return False
    parts = urlparse(uri)
    if parts.scheme not in {"http", "https"}:
        return False
    if parts.username or parts.password:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    return host in {"localhost", "127.0.0.1"}
