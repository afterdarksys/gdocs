"""Work-oriented CLI extensions, imported without Google dependencies."""
def leaf(verbs, name, common, handler):
    p = verbs.add_parser(name, parents=[common])
    p.set_defaults(func=handler)
    return p

def register(nouns, common):
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
