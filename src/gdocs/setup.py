"""Interactive onboarding using the existing OAuth validation and token storage."""

from __future__ import annotations

import sys
from pathlib import Path

from gdocs import auth
from gdocs.errors import GdocsError


def _prompt(message: str) -> str:
    print(message, end="", file=sys.stderr, flush=True)
    try:
        return input().strip()
    except EOFError:
        raise GdocsError("Setup cancelled: input ended. Run gdocs setup to try again.") from None


def _yes_no(message: str, *, default: bool) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        answer = _prompt(message + suffix).lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please enter yes or no.", file=sys.stderr)


def run_setup(client: str | None = None, readonly: bool = False) -> None:
    if not sys.stdin.isatty():
        raise GdocsError(
            "gdocs setup needs an interactive terminal. "
            "For scripts, use gdocs login --client CLIENT.json [--readonly]."
        )
    print("gdocs setup — press Ctrl-C at any time to cancel.", file=sys.stderr)
    if not client and not _yes_no("Do you already have a Desktop OAuth client JSON file?", default=False):
        steps = (
            "1. Create or select a Google Cloud project:\n"
            "   https://console.cloud.google.com/projectselector2/home/dashboard",
            "2. In that project, enable Google Drive API, Google Docs API,\n"
            "   Google Sheets API, and Google Slides API:\n"
            "   https://console.cloud.google.com/apis/library",
            "3. Configure Google Auth Platform branding and audience.\n"
            "   For a personal Google account, choose External. If the app is\n"
            "   in Testing, add your Google account as a test user:\n"
            "   https://console.cloud.google.com/auth/overview",
            "4. Create an OAuth client with application type Desktop app,\n"
            "   then download its JSON file:\n"
            "   https://console.cloud.google.com/auth/clients",
        )
        for step in steps:
            print("\n" + step, file=sys.stderr)
            _prompt("Press Enter when done: ")

    while True:
        supplied = client or _prompt("Path to the downloaded client JSON: ")
        # Accept quoted paths copied from a shell, including paths with spaces.
        path = str(Path(supplied.strip().strip("\"'")).expanduser())
        try:
            if not supplied.strip():
                raise GdocsError("Please enter a client JSON path.")
            secrets = auth.load_client_secrets(path)
            if "installed" not in secrets:
                raise GdocsError("Setup needs a Desktop app OAuth client; create and download one.")
        except (GdocsError, OSError, UnicodeError) as exc:
            if client:
                raise GdocsError(f"Cannot use client JSON: {exc}") from None
            print(f"Cannot use client JSON: {exc}", file=sys.stderr)
            continue
        break

    if not readonly:
        readonly = _yes_no("Use read-only access (disable edits, creation, and sharing)?", default=False)
    access = "read-only" if readonly else "read-write"
    if not _yes_no(f"Open Google sign-in with {access} access? This replaces any saved login.", default=True):
        raise GdocsError("Setup cancelled; saved credentials were not changed.")
    storage, _scopes = auth.login(path, readonly)
    print(f"Setup complete. Credentials saved in {storage}.", file=sys.stderr)
    print("Try: gdocs status\n     gdocs doc list", file=sys.stderr)
