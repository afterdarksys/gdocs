"""Work-oriented CLI extensions, imported without Google dependencies."""
def leaf(verbs, name, common, handler):
    p = verbs.add_parser(name, parents=[common])
    p.set_defaults(func=handler)
    return p

def register(nouns, common):
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
