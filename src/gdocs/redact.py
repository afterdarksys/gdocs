"""Redact Google access tokens and refresh tokens from text.

Threats: tokens leaked into logs, tracebacks, and error strings. Does not
protect a token that is already stored in the OS keychain or a file.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"ya29\.[0-9A-Za-z\-_]+|1//[0-9A-Za-z\-_]+")


def redact(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    return _TOKEN.sub("[redacted]", text)
