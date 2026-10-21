"""Accessible review inbox with explicit local acknowledgement and suggestion views."""
import hashlib
import json
from datetime import datetime, timezone
from gdocs.auth import config_dir
from gdocs.errors import GdocsError
from gdocs.filesafe import atomic_write, prepare_output, read_text_input


def review_path(file_id):
    return config_dir() / 'reviews' / (hashlib.sha256(file_id.encode()).hexdigest() + '.json')


def state(file_id):
    path = review_path(file_id)
    return json.loads(read_text_input(str(path), 1048576)) if path.exists() else None


def metadata(drive, file_id):
    from gdocs import services
    return services.execute(drive.files().get(fileId=file_id, fields='id,name,modifiedTime,version', supportsAllDrives=True))


def mark(target, kind='doc', tab=None, key=None):
    from gdocs.drive_ops import open_drive, resolve
    from gdocs import changes
    _, drive = open_drive(write=False)
    meta = resolve(drive, kind, target)
    before = metadata(drive, meta['id'])
    snapshot = changes.capture(kind, meta['id'], tab, key) if kind in ('doc','sheet') else None
    after = metadata(drive, meta['id'])
    if any(before.get(k) != after.get(k) for k in ('version','modifiedTime')):
        raise GdocsError('file changed during acknowledgement; review again', 3)
    record = {'id':meta['id'], 'kind':kind, 'modifiedTime':before.get('modifiedTime'),
              'version':before.get('version'), 'reviewedAt':datetime.now(timezone.utc).isoformat(), 'tab':tab, 'key':key}
    if snapshot: changes.save(snapshot, 'last-review')
    path = review_path(meta['id']); prepare_output(path, force=True)
    atomic_write(path, lambda f:f.write(json.dumps(record).encode()))
    return record


def inbox(kind='all', limit=50, recursive=False, include_clear=False, details=False):
    from gdocs.drive_ops import list_files
    from gdocs import comments, changes
    if not 1 <= limit <= 500: raise GdocsError('inbox limit must be between 1 and 500')
    candidates = []; truncated = False
    for selected_kind in (['doc','sheet','present'] if kind == 'all' else [kind]):
        files = list_files(selected_kind, limit=limit+1, recursive=recursive)
        candidates.extend((row, selected_kind) for row in files)
    candidates.sort(key=lambda pair:pair[0].get('modifiedTime',''), reverse=True)
    truncated = len(candidates) > limit
    rows = []
    for meta, selected_kind in candidates[:limit]:
        saved = state(meta['id'])
        changed = saved is None or saved.get('modifiedTime') != meta.get('modifiedTime')
        row = {'id':meta['id'], 'name':meta.get('name'), 'kind':selected_kind,
               'reviewStatus':'unreviewed' if saved is None else ('changed' if changed else 'reviewed'),
               'lastReviewed':saved.get('reviewedAt') if saved else None, 'modifiedTime':meta.get('modifiedTime')}
        try:
            threads = comments.run(meta['id'], selected_kind, unresolved=True)
            row['unresolvedComments'] = len(threads)
            if details: row['comments'] = threads
        except GdocsError as exc:
            row['commentsError'] = str(exc)
        if details and changed and saved and selected_kind in ('doc','sheet'):
            try:
                snapshot = changes.capture(selected_kind, meta['id'], saved.get('tab'), saved.get('key'))
                row['changes'] = changes.review(snapshot, 'last-review')
            except GdocsError as exc:
                row['changesError'] = str(exc)
        if include_clear or changed or row.get('unresolvedComments') or row.get('commentsError'):
            rows.append(row)
    return {'scanned':min(len(candidates), limit), 'truncated':truncated, 'items':rows,
            'note':'Most recently modified files within scope; unresolved comments remain visible after acknowledgement.'}


def suggestions(target, view='changes'):
    from gdocs.drive_ops import open_drive, resolve
    from gdocs import services
    from gdocs.extract import document_text
    from gdocs.changes import compare
    creds, drive = open_drive(write=False)
    meta = resolve(drive, 'doc', target)
    docs = services.build('docs','v1',creds).documents()
    def fetch(mode):
        return services.execute(docs.get(documentId=meta['id'], includeTabsContent=True, suggestionsViewMode=mode))
    if view in ('current','proposed'):
        mode = 'PREVIEW_WITHOUT_SUGGESTIONS' if view == 'current' else 'PREVIEW_SUGGESTIONS_ACCEPTED'
        doc = fetch(mode)
        return {'id':meta['id'], 'view':view, 'body':document_text(doc,markdown=True)}
    current = fetch('PREVIEW_WITHOUT_SUGGESTIONS')
    proposed = fetch('PREVIEW_SUGGESTIONS_ACCEPTED')
    inline = fetch('SUGGESTIONS_INLINE')
    revisions = {doc.get('revisionId') for doc in (current,proposed,inline)}
    if len(revisions) > 1: raise GdocsError('document changed while loading suggestion views; retry', 3)
    before = {'id':meta['id'], 'kind':'doc','content':document_text(current,markdown=True)}
    after = dict(before, content=document_text(proposed,markdown=True))
    return {'id':meta['id'], 'view':'suggested changes', 'textChanges':compare(before,after),
            'suggestions':suggestion_details(inline), 'note':'Read-only previews; no suggestions are accepted or rejected.'}


def suggestion_details(document):
    result = []
    def walk(value, path):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.startswith('suggested') and child:
                    result.append({'location':path, 'type':key, 'details':child})
                else: walk(child, path + '.' + key)
        elif isinstance(value, list):
            for index, child in enumerate(value): walk(child, f'{path}[{index}]')
    walk(document, 'document')
    return result
