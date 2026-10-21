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
