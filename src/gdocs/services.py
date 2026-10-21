"""Google API client construction.

Threats: discovery documents are not cached, and an API error is re-raised
from a short redacted reason. The response body is not copied into the
message, so a token that appears only in the body is not printed. Does not
retry or hide a permission failure.
"""

from __future__ import annotations

from gdocs.errors import GdocsError
from gdocs.redact import redact


def execute(request):
    """Run one generated request and translate HttpError."""

    return guard(request.execute)


def guard(func):
    """Call ``func`` and translate a Google HttpError into GdocsError."""

    try:
        return func()
    except GdocsError:
        raise
    except Exception as exc:
        translated = _from_http(exc)
        if translated is not None:
            raise translated from None
        raise


def build(api: str, version: str, creds):
    """Build a discovery client with a 60-second timeout and no cache."""

    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build as discovery_build

    http = AuthorizedHttp(creds, http=httplib2.Http(timeout=60))
    return discovery_build(api, version, http=http, cache_discovery=False)


def _from_http(exc: BaseException):
    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        return None
    if not isinstance(exc, HttpError):
        return None
    status = getattr(getattr(exc, "resp", None), "status", None) or "error"
    reason = getattr(exc, "reason", "") or ""
    if isinstance(reason, bytes):
        reason = reason.decode("utf-8", "replace")
    text = redact(str(reason)).replace("\n", " ").strip()
    if len(text) > 300:
        text = text[:300]
    return GdocsError(f"Google API error {status}: {text}", {401: 4, 403: 4, 409: 3, 412: 3, 429: 5, 500: 5, 502: 5, 503: 5, 504: 5}.get(status, 1))
