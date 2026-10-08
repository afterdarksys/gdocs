"""CLI errors and redacted failure reporting."""

from __future__ import annotations

import io
import os
import sys
import traceback

from gdocs.redact import redact


class GdocsError(Exception):
    """Expected failure. The message is safe to print."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def report_exception(exc: BaseException) -> int:
    """Print a redacted error and return the process exit code.

    Tracebacks are printed only when GDOCS_DEBUG=1, and still redacted.
    API failures must be re-raised with ``from None`` by callers so the
    original traceback cannot include an Authorization header.
    """

    if isinstance(exc, KeyboardInterrupt):
        return 130
    if isinstance(exc, GdocsError):
        print(redact(str(exc)), file=sys.stderr)
        return exc.exit_code or 1
    print(redact(f"unexpected error: {exc}"), file=sys.stderr)
    if os.environ.get("GDOCS_DEBUG") == "1":
        buffer = io.StringIO()
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=buffer)
        print(redact(buffer.getvalue()), file=sys.stderr)
    return 1
