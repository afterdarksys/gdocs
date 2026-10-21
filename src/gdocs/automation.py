"""Noninteractive operation journal: uncertain writes require reconciliation."""
import hashlib
import json
import os
from datetime import datetime, timezone
from gdocs.auth import config_dir
from gdocs.errors import GdocsError
from gdocs.filesafe import atomic_write, prepare_output, read_text_input
from gdocs.redact import redact

def run(argv, operation_id, receipt=None, preview=False):
    from gdocs.cli import build_parser
    if argv and argv[0] == '--': argv = argv[1:]
    if not argv or argv[0] in ('run','login','setup','logout','config','workspace','alias'):
        raise GdocsError('run requires a noninteractive document command')
    args = build_parser().parse_args(argv)
    fingerprint = hashlib.sha256(json.dumps(argv).encode()).hexdigest()
    if not operation_id or len(operation_id) > 200: raise GdocsError('operation ID must contain 1–200 characters')
    if receipt: prepare_output(__import__('pathlib').Path(receipt), force=False)
    if preview: return {'operation':operation_id,'fingerprint':fingerprint,'preview':True,'action':argv[0],'note':'Command validation only; use command-specific --preview for remote change details.'}
    path = config_dir() / 'operations' / (hashlib.sha256(operation_id.encode()).hexdigest() + '.json')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    record = {'operation':operation_id,'fingerprint':fingerprint,'status':'started','startedAt':datetime.now(timezone.utc).isoformat()}
    try:
        fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    except FileExistsError:
        record = json.loads(read_text_input(str(path), 50*1024*1024))
        if record.get('fingerprint') != fingerprint: raise GdocsError('operation ID was already used for different arguments',3)
        if record.get('status') != 'completed': raise GdocsError('prior operation has an uncertain outcome; reconcile remote state before using a new operation ID',3)
        if receipt:
            from pathlib import Path
            atomic_write(Path(receipt), lambda f: f.write(json.dumps(record).encode()))
        return dict(record, replayed=True)
    with os.fdopen(fd,'w') as handle:
        json.dump(record,handle); handle.flush(); os.fsync(handle.fileno())
    # Never automatically replay a write after an exception or process death.
    result = args.func(args)
    record.update(status='completed',completedAt=datetime.now(timezone.utc).isoformat(),result=result)
    encoded = redact(json.dumps(record,ensure_ascii=False)).encode()
    atomic_write(path,lambda f:f.write(encoded))
    if receipt:
        from pathlib import Path
        atomic_write(Path(receipt),lambda f:f.write(encoded))
    return record
