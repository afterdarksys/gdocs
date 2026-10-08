import pytest

from gdocs.errors import GdocsError
from gdocs.services import _from_http, guard


def test_http_error_is_redacted():
    httplib2 = pytest.importorskip("httplib2")
    from googleapiclient.errors import HttpError

    response = httplib2.Response({"status": 400, "reason": "Bad Request"})
    error = HttpError(response, b'{"error":{"message":"bad ya29.SECRETTOKEN"}}')
    translated = _from_http(error)
    assert isinstance(translated, GdocsError)
    text = str(translated)
    assert "400" in text
    assert "[redacted]" in text
    assert "SECRETTOKEN" not in text

    def fail():
        raise error

    with pytest.raises(GdocsError, match="400") as caught:
        guard(fail)
    assert "SECRETTOKEN" not in str(caught.value)
