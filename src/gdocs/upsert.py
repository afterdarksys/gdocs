"""Keyed, RAW cell updates that preserve columns owned by people."""
import json
from gdocs import sheet_ops
from gdocs.errors import GdocsError
from gdocs.filesafe import read_text_input
from gdocs.grid import column_letter, qualify_range, assert_cell_budget

def plan(grid, records, key, owned):
    if not grid or not grid[0]: raise GdocsError('sheet needs a header row')
    headers = grid[0]
    if len(set(headers)) != len(headers) or any(not h for h in headers):
        raise GdocsError('headers must be nonempty and unique')
    if key not in headers: raise GdocsError('key column is missing')
    if not owned or key in owned or len(set(owned)) != len(owned) or any(c not in headers for c in owned):
        raise GdocsError('owned columns must be unique existing columns excluding the key')
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise GdocsError('input must be a JSON array of records')
    existing = {}; key_index = headers.index(key)
    for number, row in enumerate(grid[1:], 2):
        if not any(v != '' for v in row): continue
        value = row[key_index] if key_index < len(row) else ''
        if not isinstance(value, str) or not value.strip(): raise GdocsError('existing keys must be nonempty text')
        if value in existing: raise GdocsError(f'duplicate existing key: {value}')
        existing[value] = (number, row)
    seen = set(); changes = []; added = 0; updated = set()
    for record in records:
        value = record.get(key)
        if not isinstance(value, str) or not value.strip(): raise GdocsError('input keys must be nonempty text')
        if value in seen: raise GdocsError(f'duplicate input key: {value}')
        seen.add(value)
        if set(record) - {key, *owned}: raise GdocsError('input contains columns outside declared ownership')
        for field, cell in record.items():
            if cell is None or not isinstance(cell, (str, int, float, bool)):
                raise GdocsError('cells must be strings, numbers, or booleans; use empty string to clear')
        if value in existing:
            number, row = existing[value]; fields = [c for c in owned if c in record]
        else:
            added += 1; number = len(grid) + added; row = []; fields = [key] + [c for c in owned if c in record]
        for field in fields:
            index = headers.index(field); before = row[index] if index < len(row) else ''
            after = record[field]
            if before != after:
                changes.append({'cell': f'{column_letter(index)}{number}', 'key':value, 'column':field, 'before':before, 'after':after})
                if value in existing: updated.add(value)
    assert_cell_budget([[c['after']] for c in changes])
    return {'added':added, 'updated':len(updated), 'changes':changes}

def run(target, path, key, owned, tab=None, preview=False):
    try: records = json.loads(read_text_input(path, 50*1024*1024))
    except ValueError: raise GdocsError('invalid JSON records') from None
    creds, meta, sheet = sheet_ops._open(target, write=not preview, tab=tab)
    def read():
        return sheet_ops._values_get(creds, meta['id'], qualify_range(sheet['title'], None), raw=True)
    grid = read()
    result = plan(grid, records, key, owned)
    if not preview and result['changes']:
        if read() != grid: raise GdocsError('sheet changed while planning; rerun upsert', 3)
        data = [{'range':qualify_range(sheet['title'], c['cell']), 'values':[[c['after']]]} for c in result['changes']]
        sheet_ops._batch_values(creds, meta['id'], 'RAW', data)
    return dict(result, id=meta['id'], preview=preview)
