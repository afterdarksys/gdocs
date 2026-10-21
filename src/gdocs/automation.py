"""Locked local operation journal; uncertain writes are never replayed."""
from contextlib import contextmanager
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from gdocs.auth import config_dir
from gdocs.errors import GdocsError
from gdocs.filesafe import atomic_write, prepare_output, read_text_input
from gdocs.redact import redact


def now():
    return datetime.now(timezone.utc).isoformat()


def operation_path(operation_id):
    if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 200:
        raise GdocsError('operation ID must contain 1–200 characters')
    return config_dir() / 'operations' / (hashlib.sha256(operation_id.encode()).hexdigest() + '.json')


def read_record(path):
    if not path.exists(): raise GdocsError('operation not found')
    return json.loads(read_text_input(str(path), 50*1024*1024))


def write_record(path, record):
    prepare_output(path, force=True)
    encoded = redact(json.dumps(record, ensure_ascii=False)).encode()
    atomic_write(path, lambda f:f.write(encoded))


@contextmanager
def operation_lock(path):
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = path.with_suffix('.lock')
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise GdocsError('operation is still running or locked', 3) from None
        yield
    finally:
        os.close(fd)


def execution_context():
    from gdocs.profiles import selected
    from gdocs.workspaces import active
    name, workspace = active()
    return {'profile':selected(), 'workspace':name, 'workspaceConfig':workspace,
            'auth':os.environ.get('GDOCS_AUTH','oauth'),
            'adcConfig':os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') if os.environ.get('GDOCS_AUTH') == 'adc' else None}


def receipt_copy(path, record, force=False):
    with operation_lock(path):
        prepare_output(path, force=force)
        atomic_write(path, lambda f:f.write(redact(json.dumps(record,ensure_ascii=False)).encode()))


def run(argv, operation_id, receipt=None, preview=False):
    from gdocs.cli import build_parser
    if argv and argv[0] == '--': argv = argv[1:]
    if not argv or argv[0] in ('run','login','setup','logout','config','workspace','alias','profile','operations','retention'):
        raise GdocsError('run requires a noninteractive document command')
    args = build_parser().parse_args(argv)
    path = operation_path(operation_id)
    context = execution_context()
    fingerprint = hashlib.sha256(json.dumps({'argv':argv,'context':context},sort_keys=True).encode()).hexdigest()
    if preview:
        return {'operation':operation_id,'fingerprint':fingerprint,'preview':True,'context':context,
                'note':'Command validation only; use command-specific --preview for remote change details.'}
    if receipt: prepare_output(Path(receipt), force=False)
    with operation_lock(path):
        if path.exists():
            record = read_record(path)
            if record.get('fingerprint') != fingerprint:
                raise GdocsError('operation ID was already used for different arguments/context, or a legacy journal; inspect it before choosing a new ID',3)
            if record.get('status') == 'archived':
                raise GdocsError('operation already completed; result was removed by retention and the write will not be replayed',3)
            if record.get('status') == 'not-applied':
                raise GdocsError('operation was reconciled as not applied; use a new ID for an intentional retry',3)
            if record.get('status') != 'completed':
                raise GdocsError('prior operation has an uncertain outcome; reconcile remote state before using a new operation ID',3)
            if receipt: receipt_copy(Path(receipt), record)
            return dict(record, replayed=True)
        record = {'operation':operation_id,'fingerprint':fingerprint,'context':context,'status':'started','startedAt':now()}
        write_record(path, record)
        # This durable marker survives exceptions/process death, including ambiguous writes.
        try:
            result = args.func(args)
        except BaseException as exc:
            record['lastError'] = {'type':type(exc).__name__, 'message':redact(str(exc))[:1000]}
            record['failedAt'] = now()
            write_record(path, record)
            raise
        record.update(status='completed',completedAt=now(),result=result)
        write_record(path, record)
        receipt_copy(config_dir() / 'receipts' / path.name, record, force=True)
        if receipt: receipt_copy(Path(receipt), record)
        return record


def inspect(operation_id):
    return read_record(operation_path(operation_id))


def listing(status=None):
    rows = []
    root = config_dir() / 'operations'
    if not root.exists(): return rows
    for path in sorted(root.glob('*.json')):
        record = read_record(path)
        if status and record.get('status') != status: continue
        rows.append({key:record.get(key) for key in ('operation','status','startedAt','completedAt','failedAt','reconciledAt','archivedAt')})
    return rows


def reconcile(operation_id, outcome, note, result_path=None):
    if outcome not in ('completed','not-applied'): raise GdocsError('invalid reconciliation outcome')
    if not note or not note.strip() or len(note) > 4000: raise GdocsError('provide a reconciliation note of 1–4000 characters')
    if outcome == 'completed' and not result_path: raise GdocsError('completed reconciliation requires --result with the verified result JSON')
    if outcome == 'not-applied' and result_path: raise GdocsError('--result is only valid for completed reconciliation')
    result = json.loads(read_text_input(result_path,50*1024*1024)) if result_path else None
    path = operation_path(operation_id)
    with operation_lock(path):
        record = read_record(path)
        if record.get('status') != 'started': raise GdocsError('only uncertain started operations can be reconciled',3)
        record.update(status=outcome,reconciledAt=now(),reconciliationNote=note,
                      reconciliationMethod='operator assertion after remote-state inspection')
        if outcome == 'completed': record.update(result=result,completedAt=now())
        write_record(path,record)
        receipt_copy(config_dir() / 'receipts' / path.name,record,force=True)
    return record
