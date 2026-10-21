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
