"""Folder navigation, shared-drive discovery and bounded recursive queries."""
import re
from gdocs import services
from gdocs.driveq import escape_drive_string
from gdocs.errors import GdocsError

FOLDER = 'application/vnd.google-apps.folder'
FIELDS = 'id,name,mimeType,parents,driveId,trashed,capabilities'


def folder_id(target):
    match = re.fullmatch(r'https://drive\.google\.com/drive/(?:u/\d+/)?folders/([A-Za-z0-9_-]+)(?:\?.*)?', target)
    value = match[1] if match else target
    if not re.fullmatch(r'[A-Za-z0-9_-]+', value): raise GdocsError('folder must be an ID or Drive folder URL')
    return value


def get(drive, target):
    meta = services.execute(drive.files().get(fileId=folder_id(target), fields=FIELDS, supportsAllDrives=True))
    if meta.get('mimeType') != FOLDER or meta.get('trashed'): raise GdocsError('target is not an available folder')
    return meta


def query(drive, q, fields, limit=None, drive_id=None, order='modifiedTime desc'):
    rows = []; token = None
    while True:
        kwargs = dict(q=q, fields=f'nextPageToken,incompleteSearch,files({fields})',
                      pageSize=min(100, limit-len(rows)) if limit else 100,
                      supportsAllDrives=True, includeItemsFromAllDrives=True,
                      corpora='drive' if drive_id else 'user', orderBy=order)
        if drive_id: kwargs['driveId'] = drive_id
        if token: kwargs['pageToken'] = token
        page = services.execute(drive.files().list(**kwargs))
        if page.get('incompleteSearch'): raise GdocsError('Drive returned an incomplete search; narrow the workspace')
        rows.extend(page.get('files', []))
        token = page.get('nextPageToken')
        if not token or (limit and len(rows) >= limit): return rows[:limit] if limit else rows


def descendants(drive, parent):
    found = [parent['id']]; seen = set(found)
    for folder in found:
        children = query(drive, f"trashed = false and mimeType = '{FOLDER}' and '{escape_drive_string(folder)}' in parents", 'id', drive_id=parent.get('driveId'))
        for child in children:
            if child['id'] not in seen:
                seen.add(child['id']); found.append(child['id'])
                if len(found) > 1000: raise GdocsError('recursive search exceeds 1000 folders; choose a smaller workspace')
    return found


def creation_parents(drive):
    from gdocs.workspaces import active
    _, workspace = active()
    target = workspace.get('folder')
    if not target: return {}
    parent = get(drive, target)
    if not parent.get('capabilities', {}).get('canAddChildren'):
        raise GdocsError('current account cannot create files in the workspace folder', 4)
    return {'parents': [parent['id']]}


def navigate(target):
    from gdocs.workspaces import active, load, save
    from gdocs.drive_ops import open_drive
    data = load(); name, workspace = active(data)
    if not name: raise GdocsError('select a workspace before navigating')
    _, drive = open_drive(write=False)
    if target == '..':
        current = get(drive, workspace['folder'])
        parents = current.get('parents', [])
        if len(parents) != 1: raise GdocsError('folder has no single accessible parent')
        target = parents[0]
    meta = get(drive, target)
    workspace['folder'] = meta['id']; workspace['driveId'] = meta.get('driveId')
    save(data)
    return {'workspace': name, 'folder': meta['id'], 'name': meta['name'], 'driveId': meta.get('driveId')}


def list_folder(target=None, recursive=False, limit=100):
    from gdocs.drive_ops import open_drive
    from gdocs.workspaces import active
    from gdocs.grid import list_limit
    cap = list_limit(limit)
    _, workspace = active()
    target = target or workspace.get('folder')
    if not target: raise GdocsError('provide a folder or select a workspace')
    _, drive = open_drive(write=False); parent = get(drive, target)
    ids = descendants(drive, parent) if recursive else [parent['id']]
    rows = []
    for identifier in ids:
        rows.extend(query(drive, f"trashed = false and '{escape_drive_string(identifier)}' in parents", 'id,name,mimeType,parents,modifiedTime,webViewLink', cap, parent.get('driveId')))
    return sorted(rows, key=lambda r: r.get('modifiedTime', ''), reverse=True)[:cap]


def create(name, parent=None):
    from gdocs.drive_ops import open_drive, check_title
    title = check_title(name)
    _, drive = open_drive(write=True)
    if parent:
        meta = get(drive, parent)
        if not meta.get('capabilities', {}).get('canAddChildren'): raise GdocsError('cannot add children to destination', 4)
        parents = {'parents': [meta['id']]}
    else: parents = creation_parents(drive)
    return services.execute(drive.files().create(body={'name':title, 'mimeType':FOLDER, **parents}, fields=FIELDS, supportsAllDrives=True))


def move(target, destination, kind='doc', preview=False):
    from gdocs.drive_ops import open_drive, resolve
    _, drive = open_drive(write=not preview)
    parent = get(drive, destination)
    if not parent.get('capabilities', {}).get('canAddChildren'): raise GdocsError('cannot add children to destination', 4)
    source = get(drive, target) if kind == 'folder' else resolve(drive, kind, target)
    meta = services.execute(drive.files().get(fileId=source['id'], fields=FIELDS, supportsAllDrives=True))
    if parent['id'] == meta['id']: raise GdocsError('cannot move a folder into itself')
    cross_drive = meta.get('driveId') != parent.get('driveId')
    capability = 'canMoveItemOutOfDrive' if cross_drive else 'canMoveItemWithinDrive'
    if not meta.get('capabilities', {}).get(capability): raise GdocsError('current account cannot perform this move', 4)
    if kind == 'folder' and cross_drive: raise GdocsError('cross-drive folder moves are not supported')
    if kind == 'folder' and parent['id'] in descendants(drive, meta): raise GdocsError('cannot move a folder into its descendant')
    old = meta.get('parents', [])
    result = {'id': meta['id'], 'from': old, 'to': parent['id'], 'preview': preview, 'changed': old != [parent['id']]}
    if not preview and result['changed']:
        services.execute(drive.files().update(fileId=meta['id'], addParents=parent['id'], removeParents=','.join(old), fields='id,parents,driveId', supportsAllDrives=True))
    return result


def shared_drives():
    from gdocs.drive_ops import open_drive
    _, drive = open_drive(write=False)
    rows = []; token = None
    while True:
        kwargs = {'pageSize':100, 'fields':'nextPageToken,drives(id,name,capabilities)'}
        if token: kwargs['pageToken'] = token
        page = services.execute(drive.drives().list(**kwargs)); rows.extend(page.get('drives', []))
        token = page.get('nextPageToken')
        if not token: return rows
