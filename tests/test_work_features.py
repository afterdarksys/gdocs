from gdocs.output import render, choose_output
from gdocs import reading
import pytest
from gdocs.errors import GdocsError

def test_plain_preserves_full_values():
    value = 'asset-' + 'x'*100
    assert value in render([{'Asset': value, 'Owner': 'Ryan'}], 'plain')
    assert 'Owner: Ryan' in render([{'Owner': 'Ryan'}], 'plain')

def test_section_boundaries(monkeypatch):
    from gdocs import doc_ops
    monkeypatch.setattr(doc_ops, 'view', lambda *a, **k: '# Start\na\n## Child\nb\n# End\nc')
    assert reading.read('id', 'Start') == '# Start\na\n## Child\nb'
    with pytest.raises(GdocsError): reading.read('id', 'missing')

def test_preferences(tmp_path, monkeypatch):
    monkeypatch.setenv('GDOCS_CONFIG_DIR', str(tmp_path))
    from gdocs.preferences import save
    save({'output': 'plain'})
    assert choose_output(None, True) == 'plain'
    assert choose_output('json', True) == 'json'

def test_changes_detect_records_and_preserve_baseline(tmp_path, monkeypatch):
    from gdocs.changes import compare, save, review
    monkeypatch.setenv('GDOCS_CONFIG_DIR', str(tmp_path))
    old = {'id':'x', 'kind':'sheet', 'key':'id', 'content':[{'id':'a','owner':'one'}]}
    new = dict(old, content=[{'id':'a','owner':'two'}, {'id':'b','owner':'one'}])
    save(old, 'last-review')
    assert review(new, 'last-review')['summary'] == {'added':1,'removed':0,'changed':1}
    assert review(new, 'last-review') == compare(old, new)
    with pytest.raises(GdocsError): compare(old, dict(new, content=[{'id':'a'},{'id':'a'}]))

def test_heading_changes():
    from gdocs.changes import compare
    old = {'id':'x','kind':'doc','content':'# A\nsame\n# B\nold'}
    result = compare(old, dict(old,content='# A\nsame\n# B\nnew'))
    assert result['summary']['changed'] == 1
    assert result['changed'][0]['item'] == 'B [1]'

def test_comments_pagination_and_resolve(monkeypatch):
    from gdocs import comments
    from unittest.mock import Mock
    drive = Mock()
    monkeypatch.setattr(comments, 'open_drive', lambda **kw: (None,drive))
    monkeypatch.setattr(comments, 'resolve', lambda *a: {'id':'file'})
    drive.comments.return_value.list.return_value.execute.side_effect = [
        {'comments':[{'id':'1','resolved':True}], 'nextPageToken':'next'},
        {'comments':[{'id':'2','resolved':False,'quotedFileContent':{'value':'context'}}]}]
    assert comments.run('file', unresolved=True)[0]['id'] == '2'
    assert drive.comments.return_value.list.call_args.kwargs['pageToken'] == 'next'
    comments.run('file', action='resolve', comment_id='2')
    assert drive.replies.return_value.create.call_args.kwargs['body'] == {'action':'resolve'}

def test_upsert_preserves_human_columns_and_is_repeatable():
    from gdocs.upsert import plan
    grid = [['id','severity','notes'], ['a','low','=A1']]
    records = [{'id':'a','severity':'high'},{'id':'b','severity':'low'}]
    result = plan(grid, records, 'id', ['severity'])
    assert [c['cell'] for c in result['changes']] == ['B2','A3','B3']
    assert all(c['column'] != 'notes' for c in result['changes'])
    after = [['id','severity','notes'], ['a','high','=A1'], ['b','low']]
    assert plan(after, records, 'id', ['severity'])['changes'] == []
    with pytest.raises(GdocsError): plan(grid, [{'id':'a','notes':'overwrite'}], 'id', ['severity'])
    with pytest.raises(GdocsError): plan(grid, [{'id':'a'}, {'id':'a'}], 'id', ['severity'])

def test_report_strict_template_and_rich_markdown():
    from gdocs.reports import render, parser, compile_section
    with pytest.raises(GdocsError): render('{{missing}}', {})
    assert render('{{summary}}', {'summary':'{{literal}}'}) == '{{literal}}'
    rich = parser().render('# Title\n\n|A|B|\n|-|-|\n|1|2|\n\n```\ncode\n```')
    assert '<h1>' in rich and '<table>' in rich and '<code>' in rich
    requests = compile_section('# Hi 😀\n\n[Link](https://example.com) and **bold**', 10, 'tab')
    assert requests[0]['insertText']['text'] == 'Hi 😀\nLink and bold\n'
    assert requests[0]['insertText']['location']['tabId'] == 'tab'
    assert any(r.get('updateTextStyle',{}).get('textStyle',{}).get('link') for r in requests)
    with pytest.raises(GdocsError): compile_section('|A|B|\n|-|-|\n|1|2|',1)

def test_section_bounds_preserve_neighbor():
    from gdocs.reports import section_range
    def p(start,end,text,style='NORMAL_TEXT'):
        return {'startIndex':start,'endIndex':end,'paragraph':{'paragraphStyle':{'namedStyleType':style},'elements':[{'textRun':{'content':text+'\n'}}]}}
    doc={'body':{'content':[p(1,9,'Managed','HEADING_1'),p(9,14,'old'),p(14,20,'Human','HEADING_1'),p(20,26,'notes')]}}
    assert section_range(doc,'Managed') == (None,9,14)

def test_operation_replay_and_uncertain_failure(tmp_path, monkeypatch):
    from gdocs import automation, cli
    from argparse import Namespace
    from unittest.mock import Mock
    monkeypatch.setenv('GDOCS_CONFIG_DIR',str(tmp_path))
    handler=Mock(return_value={'id':'created'})
    parser=Mock(); parser.parse_args.return_value=Namespace(func=handler)
    monkeypatch.setattr(cli,'build_parser',lambda:parser)
    automation.run(['doc','create'],'one')
    assert automation.run(['doc','create'],'one')['replayed']
    assert handler.call_count == 1
    with pytest.raises(GdocsError): automation.run(['doc','other'],'one')
    handler.side_effect=RuntimeError('connection lost')
    with pytest.raises(RuntimeError): automation.run(['doc','create'],'two')
    with pytest.raises(GdocsError,match='uncertain'): automation.run(['doc','create'],'two')
    assert handler.call_count == 2

def test_ci_error_json(monkeypatch,capsys):
    from gdocs.errors import report_exception
    import json
    monkeypatch.setenv('GDOCS_CI','1')
    assert report_exception(GdocsError('conflict',3)) == 3
    assert json.loads(capsys.readouterr().err)['error']['exitCode'] == 3

def test_evidence_detects_tampering_and_traversal(tmp_path):
    from gdocs.evidence import verify
    import hashlib,json
    payload=b'evidence'; (tmp_path/'file.docx').write_bytes(payload)
    manifest={'schemaVersion':1,'files':[{'path':'file.docx','sha256':hashlib.sha256(payload).hexdigest(),'bytes':len(payload)}]}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    assert verify(tmp_path)['verified']
    (tmp_path/'file.docx').write_bytes(b'changed')
    with pytest.raises(GdocsError,match='mismatch'): verify(tmp_path)
    manifest['files'][0]['path']='../outside'
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(GdocsError,match='path'): verify(tmp_path)

def test_workspace_scopes_and_alias_types(tmp_path,monkeypatch):
    from gdocs.preferences import save
    from gdocs.workspaces import alias_target,scope,use
    monkeypatch.setenv('GDOCS_CONFIG_DIR',str(tmp_path))
    monkeypatch.delenv('GDOCS_WORKSPACE',raising=False)
    save({'activeWorkspace':'security','workspaces':{'security':{'folder':'folder-id','aliases':{'risks':{'id':'x'*25,'kind':'sheet'}}}}})
    assert alias_target('@risks','sheet') == 'x'*25
    assert alias_target('risks','sheet') == 'x'*25
    with pytest.raises(GdocsError): alias_target('risks','doc')
    with pytest.raises(GdocsError): alias_target('@missing','doc')
    assert scope('trashed = false') == "trashed = false and 'folder-id' in parents"
    use('none'); assert scope('query') == 'query'

def test_new_command_parsers():
    from gdocs.cli import build_parser
    parser=build_parser()
    for argv in [
        ['doc','read','file','--section','Containment'],
        ['sheet','upsert','file','--key','id','--columns','severity','--json','-'],
        ['comments','resolve','file','comment'],
        ['report','render','incident','--data','data.json','--preview'],
        ['run','--id','build-1','--','doc','create','--name','Report'],
        ['evidence','collect','out','--source','doc:file'],
        ['workspace','create','security','--folder','folder-id'],
        ['alias','set','risks','file','--kind','sheet'],
    ]:
        assert callable(parser.parse_args(argv).func)

def test_upsert_preview_and_conflict_make_no_writes(tmp_path,monkeypatch):
    from gdocs import upsert
    from unittest.mock import Mock
    path=tmp_path/'findings.json'; path.write_text('[{"id":"a","severity":"high"}]')
    grid=[['id','severity','notes'],['a','low','keep']]
    monkeypatch.setattr(upsert.sheet_ops,'_open',lambda *a,**k:(None,{'id':'file'},{'title':'Findings'}))
    read=Mock(return_value=grid); write=Mock()
    monkeypatch.setattr(upsert.sheet_ops,'_values_get',read)
    monkeypatch.setattr(upsert.sheet_ops,'_batch_values',write)
    result=upsert.run('file',str(path),'id',['severity'],preview=True)
    assert result['updated'] == 1 and not write.called
    read.side_effect=[grid,[grid[0],['a','medium','keep']]]
    with pytest.raises(GdocsError,match='changed'): upsert.run('file',str(path),'id',['severity'])
    assert not write.called
    read.side_effect=[grid,grid]
    upsert.run('file',str(path),'id',['severity'])
    assert write.call_args.args[2] == 'RAW'
    assert write.call_args.args[3] == [{'range':"Findings!B2",'values':[['high']]}]

def test_report_section_api_precondition(monkeypatch):
    from gdocs import reports,drive_ops,services
    from unittest.mock import Mock
    def p(start,end,text,style):
        return {'startIndex':start,'endIndex':end,'paragraph':{'paragraphStyle':{'namedStyleType':style},'elements':[{'textRun':{'content':text}}]}}
    document={'revisionId':'revision-123','body':{'content':[p(1,9,'Managed\n','HEADING_1'),p(9,13,'old\n','NORMAL_TEXT'),p(13,19,'Human\n','HEADING_1'),p(19,24,'keep\n','NORMAL_TEXT')]}}
    service=Mock(); docs=service.documents.return_value
    docs.get.return_value.execute.return_value=document
    monkeypatch.setattr(drive_ops,'open_drive',lambda **k:(None,Mock()))
    monkeypatch.setattr(drive_ops,'resolve',lambda *a:{'id':'file'})
    monkeypatch.setattr(services,'build',lambda *a:service)
    reports.update_section('file','Managed','new',True)
    assert not docs.batchUpdate.called
    reports.update_section('file','Managed','new',False)
    body=docs.batchUpdate.call_args.kwargs['body']
    assert body['writeControl'] == {'requiredRevisionId':'revision-123'}
    assert body['requests'][0]['deleteContentRange']['range'] == {'startIndex':9,'endIndex':13}

def test_evidence_collection_and_changed_source_cleanup(tmp_path,monkeypatch):
    from gdocs import evidence,drive_ops
    from unittest.mock import Mock
    from pathlib import Path
    drive=Mock()
    meta={'id':'x'*25,'name':'Doc','version':'1','modifiedTime':'now'}
    drive.files.return_value.get.return_value.execute.return_value=meta
    monkeypatch.setattr(drive_ops,'open_drive',lambda **kw:(None,drive))
    monkeypatch.setattr(drive_ops,'resolve',lambda *args:meta)
    monkeypatch.setattr(drive_ops,'export_file',lambda kind,target,fmt,dest,force:Path(dest).write_bytes(b'export'))
    evidence.collect(['doc:file'],tmp_path/'complete',tickets=['SEC-1'])
    assert evidence.verify(tmp_path/'complete')['verified']
    drive.files.return_value.get.return_value.execute.side_effect=[meta,dict(meta,version='2')]
    with pytest.raises(GdocsError,match='changed'): evidence.collect(['doc:file'],tmp_path/'failed')
    assert not (tmp_path/'failed').exists()
    assert not list(tmp_path.glob('.gdocs-evidence-*'))

def test_adc_does_not_load_saved_oauth(monkeypatch):
    from gdocs import auth
    import google.auth
    from unittest.mock import Mock
    creds=Mock()
    monkeypatch.setenv('GDOCS_AUTH','adc')
    monkeypatch.setattr(google.auth,'default',lambda **kw:(creds,'project'))
    monkeypatch.setattr(auth,'load_stored',Mock(side_effect=AssertionError('must not load token')))
    assert auth.load_credentials() == (creds,'application-default')
