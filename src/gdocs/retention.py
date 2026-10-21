"""Preview-first local retention; operation tombstones preserve deduplication."""
from datetime import datetime, timedelta, timezone
from gdocs.auth import config_dir
from gdocs.automation import read_record, write_record, operation_lock, now
from gdocs.errors import GdocsError


def expired(value, days, current):
    if not value: return False
    try:
        instant = datetime.fromisoformat(value.replace('Z','+00:00'))
        if instant.tzinfo is None: return False
        return instant < current - timedelta(days=days)
    except (ValueError, TypeError): return False


def prune(snapshots_days=None, receipts_days=None, operations_days=None, apply=False):
    ages = {'snapshots':snapshots_days,'receipts':receipts_days,'operations':operations_days}
    if all(age is None for age in ages.values()): raise GdocsError('select at least one retention age')
    if any(age is not None and (isinstance(age,bool) or age < 1) for age in ages.values()):
        raise GdocsError('retention ages must be positive days')
    current = datetime.now(timezone.utc); actions = []; skipped = []
    for category, days in ages.items():
        if days is None: continue
        root = config_dir() / category
        if not root.exists(): continue
        if root.is_symlink(): raise GdocsError('refusing symlink retention directory')
        paths = sorted(root.glob('*/*.json' if category == 'snapshots' else '*.json'))
        for path in paths:
            if path.is_symlink() or path.parent.is_symlink(): raise GdocsError('refusing symlink retention path')
            record = read_record(path)
            if category == 'operations':
                if record.get('status') != 'completed' or not expired(record.get('completedAt'),days,current): continue
                action = {'path':str(path),'action':'compact operation; preserve deduplication'}
                if apply:
                    try:
                        with operation_lock(path):
                            latest = read_record(path)
                            if latest != record:
                                skipped.append({'path':str(path),'reason':'changed during retention'}); continue
                            kept = {k:latest[k] for k in ('operation','fingerprint','context','startedAt','completedAt','reconciledAt') if k in latest}
                            kept.update(status='archived',archivedAt=now())
                            write_record(path,kept)
                    except GdocsError as exc:
                        if exc.exit_code != 3: raise
                        skipped.append({'path':str(path),'reason':'operation locked'}); continue
            else:
                stamp = record.get('collectedAt') if category == 'snapshots' else (record.get('completedAt') or record.get('reconciledAt'))
                if not expired(stamp,days,current): continue
                action = {'path':str(path),'action':'delete '+category.rstrip('s')}
                if apply:
                    try:
                        with operation_lock(path):
                            if read_record(path) != record:
                                skipped.append({'path':str(path),'reason':'changed during retention'}); continue
                            path.unlink()
                    except GdocsError as exc:
                        if exc.exit_code != 3: raise
                        skipped.append({'path':str(path),'reason':'local state locked'}); continue
            actions.append(action)
    return {'applied':apply,'actions':actions,'skipped':skipped,
            'note':'Only active-profile local state is managed. External receipt exports, evidence packages, credentials and uncertain operations are retained.'}
