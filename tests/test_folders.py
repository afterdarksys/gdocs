from unittest.mock import Mock
import pytest
from gdocs import folders, drive_ops, preferences
from gdocs.errors import GdocsError

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('GDOCS_CONFIG_DIR', str(tmp_path))
    monkeypatch.delenv('GDOCS_PROFILE', raising=False)
    monkeypatch.delenv('GDOCS_WORKSPACE', raising=False)


def test_paginated_shared_drive_query_and_incomplete():
    drive = Mock()
    drive.files.return_value.list.return_value.execute.side_effect = [
        {'files':[{'id':'a'}], 'nextPageToken':'next'}, {'files':[{'id':'b'}]}]
    assert len(folders.query(drive, 'query', 'id', drive_id='shared')) == 2
    kwargs = drive.files.return_value.list.call_args.kwargs
    assert kwargs['corpora'] == 'drive' and kwargs['driveId'] == 'shared'
    assert kwargs['pageToken'] == 'next'
    drive.files.return_value.list.return_value.execute.side_effect = None
    drive.files.return_value.list.return_value.execute.return_value = {'incompleteSearch':True}
    with pytest.raises(GdocsError, match='incomplete'): folders.query(drive, 'query', 'id')


def test_recursive_search_sorts_globally(monkeypatch):
    preferences.save({'activeWorkspace':'work','workspaces':{'work':{'folder':'root'}}})
    drive = Mock(); monkeypatch.setattr(drive_ops,'open_drive',lambda **k:(None,drive))
    monkeypatch.setattr(folders,'get',lambda *a:{'id':'root','driveId':'shared'})
    monkeypatch.setattr(folders,'descendants',lambda *a:['root','child'])
    calls=[]
    def query(drive,q,fields,cap,drive_id):
        calls.append((q,drive_id))
        return [{'id':'a','name':'Old','modifiedTime':'2020'}] if "'root'" in q else [{'id':'b','name':'New','modifiedTime':'2026'}]
    monkeypatch.setattr(folders,'query',query)
    result=drive_ops.list_files('doc',recursive=True,limit=1)
    assert result[0]['id'] == 'b'
    assert len(calls) == 2 and all(c[1] == 'shared' for c in calls)


def test_creation_uses_workspace_and_checks_capability(monkeypatch):
    preferences.save({'activeWorkspace':'work','workspaces':{'work':{'folder':'folder'}}})
    drive=Mock()
    monkeypatch.setattr(drive_ops,'open_drive',lambda **k:(None,drive))
    drive.files.return_value.get.return_value.execute.return_value={'id':'folder','mimeType':folders.FOLDER,'capabilities':{'canAddChildren':True}}
    drive.files.return_value.create.return_value.execute.return_value={'id':'x'*25,'name':'Report'}
    drive_ops.create_file('doc','Report')
    assert drive.files.return_value.create.call_args.kwargs['body']['parents'] == ['folder']
    drive.files.return_value.create.reset_mock()
    drive.files.return_value.get.return_value.execute.return_value['capabilities']['canAddChildren']=False
    with pytest.raises(GdocsError): drive_ops.create_file('doc','Report')
    assert not drive.files.return_value.create.called


def test_move_preview_never_writes(monkeypatch):
    drive=Mock(); monkeypatch.setattr(drive_ops,'open_drive',lambda **k:(None,drive))
    monkeypatch.setattr(folders,'get',lambda *a:{'id':'new','capabilities':{'canAddChildren':True}})
    monkeypatch.setattr(drive_ops,'resolve',lambda *a:{'id':'file'})
    drive.files.return_value.get.return_value.execute.return_value={'id':'file','parents':['old'],'capabilities':{'canMoveItemWithinDrive':True}}
    assert folders.move('file','new',preview=True)['to'] == 'new'
    assert not drive.files.return_value.update.called
    folders.move('file','new')
    kwargs=drive.files.return_value.update.call_args.kwargs
    assert kwargs['addParents'] == 'new' and kwargs['removeParents'] == 'old'


def test_recursive_folder_walk_deduplicates_cycles(monkeypatch):
    monkeypatch.setattr(folders,'query',lambda d,q,*a,**k:[{'id':'child'}] if "'root'" in q else [{'id':'root'}])
    assert folders.descendants(Mock(),{'id':'root'}) == ['root','child']
