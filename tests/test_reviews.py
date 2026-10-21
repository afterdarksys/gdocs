import json
from unittest.mock import Mock
import pytest
from gdocs import reviews, drive_ops, comments, changes, services
from gdocs.errors import GdocsError


def test_inbox_comments_errors_and_truncation(monkeypatch):
    rows=[{'id':'one','name':'Runbook','modifiedTime':'2026'}, {'id':'two','name':'Old','modifiedTime':'2025'}]
    monkeypatch.setattr(drive_ops,'list_files',lambda *a,**k:rows)
    monkeypatch.setattr(reviews,'state',lambda fid:{'modifiedTime':'2026','reviewedAt':'today'})
    monkeypatch.setattr(comments,'run',lambda *a,**k:[{'id':'thread','content':'Please review'}])
    result=reviews.inbox('doc',limit=1,details=True)
    assert result['truncated'] and result['scanned'] == 1
    assert result['items'][0]['reviewStatus'] == 'reviewed'
    assert result['items'][0]['unresolvedComments'] == 1
    monkeypatch.setattr(comments,'run',Mock(side_effect=GdocsError('access denied')))
    assert reviews.inbox('doc',limit=1)['items'][0]['commentsError'] == 'access denied'


def test_acknowledge_stable_version_and_save_snapshot(monkeypatch):
    drive=Mock(); meta={'id':'file','modifiedTime':'now','version':'4'}
    monkeypatch.setattr(drive_ops,'open_drive',lambda **k:(None,drive))
    monkeypatch.setattr(drive_ops,'resolve',lambda *a:meta)
    monkeypatch.setattr(reviews,'metadata',lambda *a:meta)
    monkeypatch.setattr(changes,'capture',lambda *a:{'id':'file','kind':'doc','content':'reviewed'})
    result=reviews.mark('target')
    assert result['version'] == '4'
    assert reviews.state('file')['reviewedAt']
    assert changes.review({'id':'file','kind':'doc','content':'reviewed'},'last-review')['summary']['changed'] == 0
    monkeypatch.setattr(reviews,'metadata',Mock(side_effect=[meta,dict(meta,version='5')]))
    with pytest.raises(GdocsError,match='changed'): reviews.mark('target')
    assert reviews.state('file')['version'] == '4'


def test_suggestion_views_and_revision_conflicts(monkeypatch):
    docs=Mock(); service=Mock(); service.documents.return_value=docs
    monkeypatch.setattr(drive_ops,'open_drive',lambda **k:('creds',Mock()))
    monkeypatch.setattr(drive_ops,'resolve',lambda *a:{'id':'file'})
    monkeypatch.setattr(services,'build',lambda *a:service)
    def document(text, revision='v1'):
        return {'revisionId':revision,'body':{'content':[{'paragraph':{'elements':[{'textRun':{'content':text}}]}}]}}
    current=document('old'); proposed=document('new'); inline=document('oldnew')
    inline['body']['content'][0]['paragraph']['elements'][0]['textRun']['suggestedInsertionIds']=['s1']
    docs.get.return_value.execute.side_effect=[current,proposed,inline]
    result=reviews.suggestions('file')
    assert result['textChanges']['summary']['changed'] == 1
    assert result['suggestions'][0]['details'] == ['s1']
    modes=[c.kwargs['suggestionsViewMode'] for c in docs.get.call_args_list]
    assert modes == ['PREVIEW_WITHOUT_SUGGESTIONS','PREVIEW_SUGGESTIONS_ACCEPTED','SUGGESTIONS_INLINE']
    assert not docs.batchUpdate.called
    docs.get.return_value.execute.side_effect=[current,document('new','v2'),inline]
    with pytest.raises(GdocsError,match='changed'): reviews.suggestions('file')
