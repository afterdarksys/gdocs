"""Named local workspaces and verified file aliases."""
import os
import re
from gdocs.errors import GdocsError
from gdocs.preferences import load, save
from gdocs.driveq import escape_drive_string

def valid_name(name):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',name): raise GdocsError('name must contain 1–80 letters, digits, underscores or hyphens')
    return name

def active(data=None):
    data = load() if data is None else data
    name = os.environ.get('GDOCS_WORKSPACE') or data.get('activeWorkspace')
    if not name: return None, {}
    workspace = data.get('workspaces',{}).get(name)
    if workspace is None: raise GdocsError(f'unknown workspace: {name}')
    return name, workspace

def scope(query):
    _, workspace = active()
    folder = workspace.get('folder')
    return query + f" and '{escape_drive_string(folder)}' in parents" if folder else query

def alias_target(target,kind):
    _,workspace = active()
    explicit = target.startswith('@')
    name = target[1:] if explicit else target
    value = workspace.get('aliases',{}).get(name)
    if value is None:
        if explicit: raise GdocsError(f'alias not found: {name}')
        return target
    if value['kind'] != kind: raise GdocsError('alias refers to a different file type')
    return value['id']

def create(name,folder):
    valid_name(name)
    data=load()
    if name in data.get('workspaces',{}): raise GdocsError('workspace already exists')
    from gdocs.drive_ops import open_drive
    from gdocs import services
    # Accept a folder ID or standard Drive folder URL.
    match = re.fullmatch(r'https://drive\.google\.com/drive/(?:u/\d+/)?folders/([A-Za-z0-9_-]+)(?:\?.*)?',folder)
    folder_id = match[1] if match else folder
    if not re.fullmatch(r'[A-Za-z0-9_-]+',folder_id): raise GdocsError('folder must be an ID or Drive folder URL')
    _,drive=open_drive(write=False)
    meta=services.execute(drive.files().get(fileId=folder_id,fields='id,name,mimeType,trashed',supportsAllDrives=True))
    if meta.get('mimeType') != 'application/vnd.google-apps.folder' or meta.get('trashed'): raise GdocsError('workspace target must be an existing folder')
    data.setdefault('workspaces',{})[name]={'folder':meta['id'],'aliases':{}}
    save(data)
    return {'workspace':name,'folder':meta['id'],'active':False}

def use(name):
    data=load()
    if name != 'none' and name not in data.get('workspaces',{}): raise GdocsError('workspace not found')
    data['activeWorkspace']=None if name == 'none' else name; save(data)
    return {'activeWorkspace':data['activeWorkspace']}

def set_alias(name,target,kind):
    valid_name(name); data=load(); workspace_name,workspace=active(data)
    if not workspace_name: raise GdocsError('select a workspace before setting aliases')
    from gdocs.drive_ops import open_drive,resolve
    _,drive=open_drive(write=False); meta=resolve(drive,kind,target)
    workspace.setdefault('aliases',{})[name]={'id':meta['id'],'kind':kind}; save(data)
    return {'alias':name, 'id':meta['id'],'kind':kind,'workspace':workspace_name}

def remove_alias(name):
    data=load(); workspace_name,workspace=active(data)
    if name not in workspace.get('aliases',{}): raise GdocsError('alias not found')
    del workspace['aliases'][name]; save(data)
    return {'removed':name,'workspace':workspace_name}

def recent(limit):
    from gdocs.drive_ops import _collect
    from gdocs.driveq import KIND_MIME
    kinds=' or '.join(f"mimeType = '{mime}'" for mime in KIND_MIME.values())
    rows,_ = _collect(f'trashed = false and ({kinds})',limit)
    return rows
