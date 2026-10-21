"""Work-oriented CLI extensions, imported without Google dependencies."""
def leaf(verbs, name, common, handler):
    p = verbs.add_parser(name, parents=[common])
    p.set_defaults(func=handler)
    return p

def register(nouns, common):
    register_folders(nouns, common)
    register_profiles(nouns, common)
    register_workspaces(nouns, common)
    register_evidence(nouns, common)
    register_automation(nouns, common)
    register_reports(nouns, common)
    register_comments(nouns, common)
    register_changes(nouns, common)
    p = leaf(nouns, 'config', common, configure)
    p.add_argument('setting', choices=['output'])
    p.add_argument('value', choices=['plain', 'table', 'json', 'ndjson', 'csv'])

def configure(a):
    from gdocs.preferences import load, save
    data = load(); data[a.setting] = a.value; save(data)
    return {a.setting: a.value}

def register_editor(verbs, kind, common):
    if kind == 'doc':
        p = leaf(verbs, 'read', common, read_doc)
        p.add_argument('target')
        p.add_argument('--section')
        p.add_argument('--outline', action='store_true')

def read_doc(a):
    from gdocs.reading import read
    return read(a.target, a.section, a.outline)

def register_sheet(verbs, common, tab):
    p = leaf(verbs, 'upsert', common, upsert_sheet)
    p.add_argument('target'); p.add_argument('--json', dest='json_path', required=True)
    p.add_argument('--key', required=True); p.add_argument('--columns', required=True)
    p.add_argument('--tab'); p.add_argument('--preview', action='store_true')
    p = leaf(verbs, 'read', common, read_sheet)
    p.add_argument('target'); p.add_argument('--tab')
    p.set_defaults(output='plain')

def read_sheet(a):
    from gdocs.sheet_ops import as_json
    return as_json(a.target, tab=a.tab, limit=a.limit)


def register_changes(nouns, common):
    for name in ('snapshot', 'changes'):
        p = leaf(nouns, name, common, run_changes)
        p.add_argument('target'); p.add_argument('--kind', choices=['doc','sheet'], default='doc')
        p.add_argument('--tab'); p.add_argument('--key')
        p.add_argument('--name' if name == 'snapshot' else '--since', dest='baseline', default='last-review')
        p.add_argument('--summary', action='store_true')
        p.set_defaults(change_action=name)

def run_changes(a):
    from gdocs.changes import capture, save, review
    current = capture(a.kind, a.target, a.tab, a.key)
    return save(current, a.baseline) if a.change_action == 'snapshot' else review(current, a.baseline, a.summary)


def register_comments(nouns, common):
    root = nouns.add_parser('comments')
    verbs = root.add_subparsers(dest='comment_action', required=True)
    for action in ('list','add','reply','resolve'):
        p = leaf(verbs, action, common, run_comments)
        p.add_argument('target'); p.add_argument('--kind', choices=['doc','sheet','present'], default='doc')
        if action in ('reply','resolve'): p.add_argument('comment_id')
        if action in ('add','reply'): p.add_argument('text')
        if action == 'list': p.add_argument('--unresolved', action='store_true')

def run_comments(a):
    from gdocs.comments import run
    return run(a.target, a.kind, a.comment_action, getattr(a,'comment_id',None), getattr(a,'text',None), getattr(a,'unresolved',False))


def upsert_sheet(a):
    from gdocs.upsert import run
    return run(a.target, a.json_path, a.key, [c.strip() for c in a.columns.split(',')], a.tab, a.preview)


def register_reports(nouns, common):
    root = nouns.add_parser('report'); verbs = root.add_subparsers(dest='report_action',required=True)
    p = leaf(verbs,'render',common,render_report)
    p.add_argument('template'); p.add_argument('--data',required=True)
    p.add_argument('--name'); p.add_argument('--into'); p.add_argument('--section')
    p.add_argument('--preview',action='store_true')

def render_report(a):
    from gdocs.reports import run
    return run(a.template,a.data,a.name,a.into,a.section,a.preview)


def register_automation(nouns, common):
    import argparse
    p = leaf(nouns,'run',common,run_automation)
    p.add_argument('--id',dest='operation_id',required=True)
    p.add_argument('--receipt'); p.add_argument('--preview',action='store_true')
    p.add_argument('command',nargs=argparse.REMAINDER)

def run_automation(a):
    from gdocs.automation import run
    return run(a.command,a.operation_id,a.receipt,a.preview)


def register_evidence(nouns,common):
    root = nouns.add_parser('evidence'); verbs = root.add_subparsers(dest='evidence_action',required=True)
    p = leaf(verbs,'collect',common,collect_evidence)
    p.add_argument('dest'); p.add_argument('--source',action='append',required=True)
    p.add_argument('--ticket',action='append',default=[]); p.add_argument('--control',action='append',default=[])
    p = leaf(verbs,'verify',common,verify_evidence); p.add_argument('directory')

def collect_evidence(a):
    from gdocs.evidence import collect
    return collect(a.source,a.dest,a.ticket,a.control)

def verify_evidence(a):
    from gdocs.evidence import verify
    return verify(a.directory)


def register_workspaces(nouns,common):
    root=nouns.add_parser('workspace'); verbs=root.add_subparsers(dest='workspace_action',required=True)
    p=leaf(verbs,'create',common,workspace_command); p.add_argument('name'); p.add_argument('--folder',required=True)
    p=leaf(verbs,'use',common,workspace_command); p.add_argument('name')
    leaf(verbs,'list',common,workspace_command)
    leaf(verbs,'recent',common,workspace_command)
    root=nouns.add_parser('alias'); verbs=root.add_subparsers(dest='alias_action',required=True)
    p=leaf(verbs,'set',common,alias_command); p.add_argument('name'); p.add_argument('target'); p.add_argument('--kind',choices=['doc','sheet','present'],default='doc')
    p=leaf(verbs,'remove',common,alias_command); p.add_argument('name')
    leaf(verbs,'list',common,alias_command)

def workspace_command(a):
    from gdocs import workspaces as w
    if a.workspace_action == 'create': return w.create(a.name,a.folder)
    if a.workspace_action == 'use': return w.use(a.name)
    if a.workspace_action == 'recent': return w.recent(a.limit)
    data=w.load(); active,_=w.active(data)
    return [{'workspace':name,'folder':v['folder'],'active':name == active} for name,v in data.get('workspaces',{}).items()]

def alias_command(a):
    from gdocs import workspaces as w
    if a.alias_action == 'set': return w.set_alias(a.name,a.target,a.kind)
    if a.alias_action == 'remove': return w.remove_alias(a.name)
    _, workspace=w.active()
    return [{'alias':name,**v} for name,v in workspace.get('aliases',{}).items()]


def register_profiles(nouns, common):
    root = nouns.add_parser('profile')
    verbs = root.add_subparsers(dest='profile_action', required=True)
    p = leaf(verbs, 'create', common, profile_command)
    p.add_argument('name'); p.add_argument('--email')
    p = leaf(verbs, 'use', common, profile_command); p.add_argument('name')
    leaf(verbs, 'list', common, profile_command)

def profile_command(a):
    from gdocs import profiles
    if a.profile_action == 'create': return profiles.create(a.name, a.email)
    if a.profile_action == 'use': return profiles.use(a.name)
    return profiles.listing()


def register_folders(nouns, common):
    root = nouns.add_parser('folder'); verbs = root.add_subparsers(dest='folder_action', required=True)
    p = leaf(verbs, 'list', common, folder_command); p.add_argument('target', nargs='?'); p.add_argument('--recursive', action='store_true')
    p = leaf(verbs, 'create', common, folder_command); p.add_argument('name'); p.add_argument('--parent')
    p = leaf(verbs, 'cd', common, folder_command); p.add_argument('target')
    leaf(verbs, 'pwd', common, folder_command)
    p = leaf(verbs, 'move', common, folder_command); p.add_argument('target'); p.add_argument('--to', required=True)
    p.add_argument('--kind', choices=['doc','sheet','present','folder'], default='doc'); p.add_argument('--preview', action='store_true')
    leaf(nouns, 'drives', common, list_drives)

def list_drives(a):
    from gdocs.folders import shared_drives
    return shared_drives()

def folder_command(a):
    from gdocs import folders
    if a.folder_action == 'list': return folders.list_folder(a.target, a.recursive, a.limit)
    if a.folder_action == 'create': return folders.create(a.name, a.parent)
    if a.folder_action == 'cd': return folders.navigate(a.target)
    if a.folder_action == 'move': return folders.move(a.target, a.to, a.kind, a.preview)
    from gdocs.workspaces import active
    name, workspace = active()
    return {'workspace':name, 'folder':workspace.get('folder')}
