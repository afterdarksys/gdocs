"""Explicit local review baselines; reading changes never advances a baseline."""
import hashlib
import json
import re
from datetime import datetime, timezone
from gdocs.auth import config_dir
from gdocs.errors import GdocsError
from gdocs.filesafe import atomic_write, prepare_output, read_text_input
from gdocs.reading import sections

def capture(kind, target, tab=None, key=None):
    from gdocs import doc_ops, sheet_ops, slide_ops
    if kind == 'doc':
        raw = doc_ops.view(target, raw=True)
        from gdocs.extract import document_text
        return {'id': raw['documentId'], 'kind': kind, 'content': document_text(raw, markdown=True)}
    if kind == 'sheet':
        creds, meta, sheet = sheet_ops._open(target, write=False, tab=tab)
        grid = sheet_ops._load_grid(creds, meta['id'], sheet['title'], raw=True, limit=None, strict=True)
        from gdocs.grid import records_from_grid
        records = records_from_grid(grid)
        if key: keyed(records, key)
        return {'id': meta['id'], 'kind': kind, 'tab': sheet['title'], 'key': key, 'content': records}
    raise GdocsError('snapshots support doc and sheet')

def path_for(snapshot, name):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', name):
        raise GdocsError('baseline name must contain 1–80 letters, digits, underscores or hyphens')
    identity = json.dumps([snapshot['kind'], snapshot['id'], snapshot.get('tab')])
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return config_dir() / 'snapshots' / digest / (name + '.json')

def save(snapshot, name):
    path = path_for(snapshot, name)
    payload = dict(snapshot, collectedAt=datetime.now(timezone.utc).isoformat())
    prepare_output(path, force=True)
    atomic_write(path, lambda f: f.write(json.dumps(payload, ensure_ascii=False).encode()))
    return {'baseline': name, 'id': snapshot['id'], 'saved': str(path)}

def keyed(records, key):
    out = {}
    for record in records:
        value = record.get(key)
        if value is None or str(value).strip() == '':
            raise GdocsError(f'missing record key: {key}')
        value = str(value)
        if value in out: raise GdocsError(f'duplicate record key: {value}')
        out[value] = record
    return out

def heading_blocks(text):
    lines = text.splitlines(); heads = sections(text)
    blocks = {'Introduction': '\n'.join(lines[:heads[0]['line']]) if heads else text}
    counts = {}
    for i, h in enumerate(heads):
        title = h['heading']; counts[title] = counts.get(title, 0) + 1
        label = f"{title} [{counts[title]}]"
        end = heads[i+1]['line'] if i+1 < len(heads) else len(lines)
        blocks[label] = '\n'.join(lines[h['line']:end])
    return blocks

def compare(old, new):
    if any(old.get(k) != new.get(k) for k in ('id','kind','tab','key')):
        raise GdocsError('baseline identity or record key differs')
    if new['kind'] == 'doc':
        before, after = heading_blocks(old['content']), heading_blocks(new['content'])
    elif new.get('key'):
        before, after = keyed(old['content'], new['key']), keyed(new['content'], new['key'])
    else:
        before = {str(i): r for i,r in enumerate(old['content'], 2)}
        after = {str(i): r for i,r in enumerate(new['content'], 2)}
    added = [{'item': k, 'after': v} for k,v in after.items() if k not in before]
    removed = [{'item': k, 'before': v} for k,v in before.items() if k not in after]
    changed = [{'item': k, 'before': before[k], 'after': v} for k,v in after.items() if k in before and before[k] != v]
    return {'summary': {'added': len(added), 'removed': len(removed), 'changed': len(changed)}, 'added': added, 'removed': removed, 'changed': changed}

def review(snapshot, name, summary=False):
    path = path_for(snapshot, name)
    if not path.exists(): raise GdocsError('baseline not found; run snapshot first')
    old = json.loads(read_text_input(str(path), 50*1024*1024))
    result = compare(old, snapshot)
    return result['summary'] if summary else result
