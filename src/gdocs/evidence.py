"""Collected exports with hashes and source metadata, never provenance claims."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime, timezone
from gdocs.errors import GdocsError
from gdocs.filesafe import read_bounded, read_text_input

def now(): return datetime.now(timezone.utc).isoformat()

def collect(sources, dest, tickets=(), controls=()):
    from gdocs.drive_ops import open_drive, resolve, export_file
    from gdocs import services
    parsed = []
    for source in sources:
        kind, sep, target = source.partition(':')
        if not sep or kind not in ('doc','sheet','present') or not target:
            raise GdocsError('sources must be doc:TARGET, sheet:TARGET or present:TARGET')
        parsed.append((kind,target))
    destination = Path(dest)
    if destination.exists() or destination.is_symlink(): raise GdocsError('evidence destination must not exist')
    if destination.parent.is_symlink(): raise GdocsError('refusing symlink parent')
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.gdocs-evidence-',dir=destination.parent))
    manifest = {'schemaVersion':1,'startedAt':now(),'tickets':list(tickets),'controls':list(controls),'files':[],'description':'Collected exports; hashes verify package integrity, not source authenticity or a simultaneous snapshot.'}
    try:
        _, drive = open_drive(write=False)
        for index,(kind,target) in enumerate(parsed,1):
            meta = resolve(drive,kind,target)
            def version():
                return services.execute(drive.files().get(fileId=meta['id'],fields='id,name,mimeType,modifiedTime,version,webViewLink',supportsAllDrives=True))
            before = version(); started = now()
            fmt = {'doc':'docx','sheet':'xlsx','present':'pptx'}[kind]
            filename = f'{index:03d}-{kind}.{fmt}'
            export_file(kind,meta['id'],fmt,str(staging/filename),False)
            after = version()
            if any(before.get(k) != after.get(k) for k in ('version','modifiedTime')):
                raise GdocsError('source changed during collection; rerun evidence collection',3)
            payload = read_bounded(staging/filename,200*1024*1024)
            manifest['files'].append({'path':filename,'kind':kind,'source':before,'startedAt':started,'collectedAt':now(),'sha256':hashlib.sha256(payload).hexdigest(),'bytes':len(payload)})
        manifest['completedAt'] = now()
        from gdocs.filesafe import atomic_write
        atomic_write(staging/'manifest.json',lambda f:f.write(json.dumps(manifest,indent=2).encode()))
        # Do not merge with an existing directory.
        if destination.exists(): raise GdocsError('evidence destination appeared during collection')
        os.rename(staging,destination)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return {'directory':str(destination),'files':len(manifest['files']),'manifest':str(destination/'manifest.json')}

def verify(directory):
    root = Path(directory)
    manifest = json.loads(read_text_input(str(root/'manifest.json'),5*1024*1024))
    if manifest.get('schemaVersion') != 1 or not isinstance(manifest.get('files'),list): raise GdocsError('unsupported evidence manifest')
    checked = []; seen = set()
    for item in manifest['files']:
        name = item.get('path')
        if not isinstance(name,str) or Path(name).name != name or name in ('.','..','manifest.json') or name in seen:
            raise GdocsError('invalid or duplicate evidence path')
        seen.add(name)
        payload = read_bounded(root/name,200*1024*1024)
        if hashlib.sha256(payload).hexdigest() != item.get('sha256') or len(payload) != item.get('bytes'):
            raise GdocsError(f'evidence integrity mismatch: {name}')
        checked.append(name)
    return {'verified':True,'files':checked,'note':'Verifies files against this manifest; does not authenticate the manifest.'}
