from argparse import Namespace
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import Mock
import pytest
from gdocs import automation, cli, retention, changes, preferences
from gdocs.errors import GdocsError

@pytest.fixture
def handler(monkeypatch):
    handler = Mock(return_value={'id':'created-file'})
    parser = Mock(); parser.parse_args.return_value = Namespace(func=handler)
    monkeypatch.setattr(cli,'build_parser',lambda:parser)
    return handler


def test_reconcile_completed_preserves_no_replay(handler,tmp_path):
    handler.side_effect=RuntimeError('connection lost')
    with pytest.raises(RuntimeError): automation.run(['doc','create'],'job')
    assert automation.inspect('job')['lastError']['type'] == 'RuntimeError'
    result=tmp_path/'verified.json'; result.write_text('{"id":"verified-file"}')
    automation.reconcile('job','completed','Verified matching document ID',str(result))
    replay=automation.run(['doc','create'],'job')
    assert replay['replayed'] and replay['result']['id'] == 'verified-file'
    assert handler.call_count == 1
    with pytest.raises(GdocsError): automation.reconcile('job','not-applied','cannot alter completed record')


def test_live_operation_cannot_be_reconciled(handler):
    path=automation.operation_path('job')
    automation.write_record(path,{'operation':'job','status':'started'})
    with automation.operation_lock(path):
        with pytest.raises(GdocsError,match='locked'):
            automation.reconcile('job','not-applied','Checked remote state')
    automation.reconcile('job','not-applied','Confirmed no remote write')
    assert automation.inspect('job')['status'] == 'not-applied'


def test_replay_context_is_bound_to_workspace(handler):
    automation.run(['doc','create'],'job')
    preferences.save({'activeWorkspace':'work','workspaces':{'work':{'folder':'new-folder'}}})
    with pytest.raises(GdocsError,match='context'): automation.run(['doc','create'],'job')
    assert handler.call_count == 1


def test_retention_preview_compaction_and_uncertain_preservation(handler):
    automation.run(['doc','create'],'done')
    path=automation.operation_path('done'); record=automation.read_record(path)
    old=(datetime.now(timezone.utc)-timedelta(days=120)).isoformat()
    record['completedAt']=old; automation.write_record(path,record)
    uncertain=automation.operation_path('uncertain')
    automation.write_record(uncertain,{'status':'started','startedAt':old})
    snapshot={'id':'file','kind':'doc','content':'private content'}
    changes.save(snapshot,'last-review'); snap_path=changes.path_for(snapshot,'last-review')
    snap=automation.read_record(snap_path); snap['collectedAt']=old; automation.write_record(snap_path,snap)
    receipt=automation.config_dir()/'receipts'/path.name
    automation.write_record(receipt,record)
    plan=retention.prune(90,90,90)
    assert len(plan['actions']) == 3 and snap_path.exists()
    retention.prune(90,90,90,True)
    assert not snap_path.exists() and not receipt.exists()
    archived=automation.inspect('done')
    assert archived['status'] == 'archived' and 'result' not in archived
    assert automation.inspect('uncertain')['status'] == 'started'
    with pytest.raises(GdocsError,match='already completed'): automation.run(['doc','create'],'done')
    assert handler.call_count == 1


def test_retention_skips_locked_operations(handler):
    automation.run(['doc','create'],'job')
    path=automation.operation_path('job'); record=automation.read_record(path)
    record['completedAt']='2000-01-01T00:00:00+00:00'; automation.write_record(path,record)
    with automation.operation_lock(path):
        result=retention.prune(operations_days=1,apply=True)
    assert result['skipped'][0]['reason'] == 'operation locked'
    assert automation.inspect('job')['status'] == 'completed'


def test_new_cli_parsers():
    parser=cli.build_parser()
    for argv in [
        ['profile','create','work','--email','work@example.com'],
        ['folder','list','--recursive'], ['folder','move','file','--to','folder','--preview'],
        ['doc','search','risk','--recursive'], ['inbox','--details','--output','plain'],
        ['review','mark','file'], ['doc','suggestions','file','--view','proposed'],
        ['operations','inspect','job'],
        ['operations','reconcile','job','--outcome','not-applied','--note','Verified'],
        ['retention','prune','--snapshots-days','30'],
    ]:
        assert callable(parser.parse_args(argv).func)
