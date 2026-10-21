import io
import json
from urllib.error import HTTPError, URLError
from unittest.mock import Mock
import pytest
from gdocs.jira_http import Client, NoRedirect, authorization, scrub
from gdocs.errors import GdocsError

class Response(io.BytesIO):
    def __init__(self,data,status=200,headers=None):
        super().__init__(data); self.status=status; self.headers=headers or {'content-type':'application/json'}

def client(response):
    opener=Mock(); opener.open.return_value=response
    return Client('https://jira.example.com/context','Bearer test-secret','test-secret',opener=opener)

def test_auth_and_redaction():
    header=authorization('cloud','engineer@example.com','secret-value')
    assert header.startswith('Basic ')
    value={'Authorization':header,'nested':{'api_token':'other'},'message':'secret-value '+header}
    output=json.dumps(scrub(value,('secret-value',header)))
    assert 'secret-value' not in output and header not in output and 'other' not in output

def test_trace_omits_query_values_and_cookies():
    c=client(Response(b'{"token":"anything","summary":"test-secret"}',headers={'set-cookie':'session=hidden','x-arequestid':'req1'}))
    result=c.get('/rest/api/3/myself',{'fields':'private-query'})
    assert result['ok'] and result['headers'] == {'x-arequestid':'req1'}
    assert result['trace']['queryKeys'] == ['fields']
    assert 'private-query' not in json.dumps(result)
    assert 'test-secret' not in json.dumps(result)
    request=c.opener.open.call_args.args[0]
    assert request.full_url.startswith('https://jira.example.com/context/rest/api/3/')

def test_redirect_is_not_followed_and_path_is_pinned():
    assert NoRedirect().redirect_request(None,None,302,'Found',{},'https://evil.test') is None
    c=client(Response(b'{}',302))
    assert not c.get('/rest/api/3/myself')['ok']
    for path in ('https://evil.test','//evil.test','/rest/api/3/../myself','/rest/api/3/%2e%2e/myself','/rest/api/3/myself?token=x'):
        with pytest.raises(GdocsError): c.get(path)
    with pytest.raises(GdocsError): c.get('/rest/api/3/myself',{'api_token':'x'})

def test_failure_diagnostics_do_not_echo_html_or_exception():
    c=client(Response(b'<html>test-secret</html>',403))
    assert c.get('/rest/api/3/myself')['errorType'] == 'non-json'
    c.opener.open.side_effect=URLError('test-secret proxy failure')
    result=c.get('/rest/api/3/myself')
    assert result['errorType'] == 'connection' and 'test-secret' not in json.dumps(result)

def test_http_error_body_is_redacted():
    c=client(None)
    c.opener.open.side_effect=HTTPError('https://jira.example.com',429,'Too many requests',{'retry-after':'30'},io.BytesIO(b'{"errorMessages":["test-secret"]}'))
    result=c.get('/rest/api/3/myself')
    assert result['status'] == 429 and result['headers']['retry-after'] == '30'
    assert 'test-secret' not in json.dumps(result)
