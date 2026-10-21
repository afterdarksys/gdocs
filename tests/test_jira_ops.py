import json
from unittest.mock import Mock
import pytest
from gdocs import jira_ops, preferences, profiles
from gdocs.cli import main
from gdocs.errors import GdocsError

@pytest.fixture(autouse=True)
def environment(monkeypatch):
    for name in ('JIRA_URL','JIRA_DEPLOYMENT','JIRA_EMAIL','JIRA_CLOUD_ID','JIRA_TOKEN_ENV','JIRA_API_TOKEN','JIRA_PAT','GDOCS_PROFILE'):
        monkeypatch.delenv(name,raising=False)


def test_config_is_profile_local_and_never_stores_token(monkeypatch):
    monkeypatch.setenv('JIRA_API_TOKEN','secret-value')
    jira_ops.configure('https://example.atlassian.net',email='engineer@example.com',cloud_id='cloud-123')
    assert 'secret-value' not in json.dumps(preferences.load())
    client,api,_=jira_ops.connect()
    assert client.base == 'https://api.atlassian.com/ex/jira/cloud-123' and api == '/rest/api/3'
    profiles.create('other'); profiles.use('other')
    with pytest.raises(GdocsError): jira_ops.status()
    jira_ops.configure('https://jira.example.com/jira',deployment='datacenter')
    monkeypatch.setenv('JIRA_PAT','dc-secret')
    client,api,_=jira_ops.connect()
    assert api == '/rest/api/2' and client.authorization == 'Bearer dc-secret'
    assert 'dc-secret' not in repr(client)


def test_cloud_search_uses_cursor_and_preserves_jql(monkeypatch):
    client=Mock()
    client.get.side_effect=[
        {'ok':True,'status':200,'data':{'issues':[{'key':'SEC-1'}],'nextPageToken':'page2'}},
        {'ok':True,'status':200,'data':{'issues':[{'key':'SEC-2'}],'isLast':True}},
    ]
    monkeypatch.setattr(jira_ops,'connect',lambda *a:(client,'/rest/api/3',{'deployment':'cloud'}))
    jql='project = SEC AND summary ~ "auth"'
    result=jira_ops.search(jql,limit=10)
    assert result['count'] == 2 and not result['truncated']
    assert client.get.call_args_list[0].args[0] == '/rest/api/3/search/jql'
    assert client.get.call_args_list[1].args[1]['nextPageToken'] == 'page2'
    assert client.get.call_args_list[0].args[1]['jql'] == jql


def test_datacenter_pagination_and_partial_failure(monkeypatch):
    client=Mock()
    client.get.side_effect=[{'ok':True,'status':200,'data':{'issues':[{'key':'SEC-1'}],'total':2}},
                            {'ok':False,'status':403,'data':{'errorMessages':['denied']}}]
    monkeypatch.setattr(jira_ops,'connect',lambda *a:(client,'/rest/api/2',{'deployment':'datacenter'}))
    result=jira_ops.search('project = SEC')
    assert result['partial'] and result.exit_code == 4
    assert client.get.call_args_list[1].args[1]['startAt'] == 1


def test_doctor_reports_all_checks_and_exit_status(monkeypatch,capsys):
    client=Mock()
    client.get.side_effect=[{'ok':True,'status':200},{'ok':False,'status':401},
                            {'ok':False,'status':403},{'ok':False,'status':404}]
    monkeypatch.setattr(jira_ops,'connect',lambda *a:(client,'/rest/api/3',{'deployment':'cloud'}))
    assert main(['jira','doctor','--issue','SEC-1','--output','json']) == 4
    result=json.loads(capsys.readouterr().out)
    assert len(result['checks']) == 4 and not result['ok']


def test_transitions_only_inspects_metadata(monkeypatch):
    client=Mock(); client.get.return_value={'ok':True,'status':200,'data':{'transitions':[]}}
    monkeypatch.setattr(jira_ops,'connect',lambda *a:(client,'/rest/api/2',{}))
    result=jira_ops.inspect_resource('transitions','SEC-1')
    assert result.exit_code == 0
    assert client.get.call_args.args == ('/rest/api/2/issue/SEC-1/transitions',{'expand':'transitions.fields'})


def test_bad_identifiers_fail_before_connection(monkeypatch):
    connect=Mock(); monkeypatch.setattr(jira_ops,'connect',connect)
    with pytest.raises(GdocsError): jira_ops.inspect_resource('issue','../myself')
    assert not connect.called


def test_repeated_cursor_fails(monkeypatch):
    client=Mock(); client.get.return_value={'ok':True,'status':200,'data':{'issues':[{'key':'SEC-1'}],'nextPageToken':'same'}}
    monkeypatch.setattr(jira_ops,'connect',lambda *a:(client,'/rest/api/3',{'deployment':'cloud'}))
    with pytest.raises(GdocsError,match='repeated'): jira_ops.search('project=SEC')


def test_transport_failures_keep_transient_exit_and_journal_refuses_diagnostics():
    from gdocs.automation import run
    result=jira_ops.DiagnosticResult(ok=False,checks=[{'status':None,'errorType':'timeout'}])
    assert result.exit_code == 5
    with pytest.raises(GdocsError,match='noninteractive document command'):
        run(['jira','doctor'],'diagnostic-run')
