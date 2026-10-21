"""Drive comment threads with pagination and explicit resolution."""
from gdocs import services
from gdocs.drive_ops import open_drive, resolve
from gdocs.errors import GdocsError

FIELDS = 'id,content,createdTime,modifiedTime,resolved,author(displayName,emailAddress),quotedFileContent,replies(id,content,createdTime,action,author(displayName,emailAddress))'

def run(target, kind='doc', action='list', comment_id=None, text=None, unresolved=False):
    if action in ('add','reply') and (not text or len(text) > 50000):
        raise GdocsError('comment text must contain 1–50000 characters')
    if action in ('reply','resolve') and not comment_id:
        raise GdocsError('comment ID is required')
    _, drive = open_drive(write=action != 'list')
    meta = resolve(drive, kind, target)
    file_id = meta['id']
    if action == 'list':
        rows = []; token = None
        while True:
            kwargs = {'fileId': file_id, 'fields': f'nextPageToken,comments({FIELDS})', 'pageSize': 100, 'includeDeleted': False}
            if token: kwargs['pageToken'] = token
            page = services.execute(drive.comments().list(**kwargs))
            rows.extend(c for c in page.get('comments', []) if not unresolved or not c.get('resolved', False))
            token = page.get('nextPageToken')
            if not token: return rows
    if action == 'add':
        return services.execute(drive.comments().create(fileId=file_id, body={'content':text}, fields=FIELDS))
    body = {'action':'resolve'} if action == 'resolve' else {'content':text}
    return services.execute(drive.replies().create(fileId=file_id, commentId=comment_id, body=body, fields='id,content,action,createdTime'))
