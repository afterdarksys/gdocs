"""Work-oriented CLI extensions, imported without Google dependencies."""
def leaf(verbs, name, common, handler):
    p = verbs.add_parser(name, parents=[common])
    p.set_defaults(func=handler)
    return p

def register(nouns, common):
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
