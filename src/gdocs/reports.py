"""Strict data templates, formatted HTML publishing, and revision-checked sections."""
import html
import json
import re
from gdocs.errors import GdocsError
from gdocs.filesafe import read_text_input

TEMPLATES = {
    'security-weekly': '# Security update: {{period}}\n\n## Summary\n{{summary}}\n\n## Findings\n{{findings}}\n\n## Next steps\n{{next_steps}}\n',
    'threat-model': '# Threat model: {{system}}\n\n## Scope\n{{scope}}\n\n## Trust boundaries\n{{boundaries}}\n\n## Threats\n{{threats}}\n\n## Mitigations\n{{mitigations}}\n',
    'incident': '# Incident: {{incident_id}}\n\n## Impact\n{{impact}}\n\n## Timeline\n{{timeline}}\n\n## Response\n{{response}}\n\n## Follow-up\n{{follow_up}}\n',
    'architecture-review': '# Architecture review: {{system}}\n\n## Design\n{{design}}\n\n## Security considerations\n{{security}}\n\n## Decisions\n{{decisions}}\n',
}

def parser():
    from markdown_it import MarkdownIt
    return MarkdownIt('commonmark', {'html':False}).enable('table')

def render(template, data):
    if not isinstance(data, dict): raise GdocsError('template data must be a JSON object')
    def replace(match):
        key = match[1]
        if key not in data: raise GdocsError(f'missing template field: {key}')
        value = data[key]
        return value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
    return re.sub(r'\{\{\s*([A-Za-z0-9_]+)\s*\}\}', replace, template)

def run(template, data_path, name=None, into=None, section=None, preview=False):
    source = TEMPLATES.get(template)
    if source is None: source = read_text_input(template, 5*1024*1024)
    data = json.loads(read_text_input(data_path, 5*1024*1024))
    markdown = render(source, data)
    if bool(into) != bool(section): raise GdocsError('--into and --section must be supplied together')
    if into: return update_section(into, section, markdown, preview)
    rendered = '<!doctype html><html><body>' + parser().render(markdown) + '</body></html>'
    if preview: return {'markdown':markdown, 'html':rendered}
    if not name: raise GdocsError('new reports require --name')
    from gdocs.drive_ops import open_drive, check_title, _creation_parents
    from gdocs.driveq import KIND_MIME, FILE_FIELDS, file_row
    from gdocs import services
    from googleapiclient.http import MediaInMemoryUpload
    _, drive = open_drive(write=True)
    return file_row(services.execute(drive.files().create(
        body={'name':check_title(name), 'mimeType':KIND_MIME['doc'], **_creation_parents(drive)},
        media_body=MediaInMemoryUpload(rendered.encode(), mimetype='text/html'),
        fields=FILE_FIELDS, supportsAllDrives=True)))

def utf16(text): return len(text.encode('utf-16-le')) // 2

def compile_section(markdown, start, tab_id=None):
    tokens = parser().parse(markdown)
    if any(t.type == 'table_open' for t in tokens):
        raise GdocsError('tables are supported in new reports; section updates currently require paragraphs, headings, lists or code')
    text = ''; styles = []; paragraph_style = 'NORMAL_TEXT'; bullet = 0; ordered = False
    def rng(a,b):
        return dict(startIndex=a,endIndex=b, **({'tabId':tab_id} if tab_id else {}))
    for token in tokens:
        if token.type == 'heading_open': paragraph_style = 'HEADING_' + token.tag[1:]
        if token.type in ('bullet_list_open','ordered_list_open'):
            bullet += 1; ordered = token.type == 'ordered_list_open'
        if token.type in ('bullet_list_close','ordered_list_close'): bullet -= 1
        if token.type not in ('inline','fence','code_block'): continue
        begin = start + utf16(text); content = ''; active = {}
        if token.type in ('fence','code_block'):
            content = token.content.rstrip('\n')
            if content: styles.append({'updateTextStyle':{'range':rng(begin,begin+utf16(content)), 'textStyle':{'weightedFontFamily':{'fontFamily':'Courier New'}}, 'fields':'weightedFontFamily'}})
        else:
            for child in token.children or []:
                if child.type in ('strong_open','em_open','link_open'):
                    field = {'strong_open':'bold','em_open':'italic','link_open':'link'}[child.type]
                    active[field] = {'url':child.attrGet('href')} if field == 'link' else True
                    continue
                if child.type in ('strong_close','em_close','link_close'):
                    active.pop({'strong_close':'bold','em_close':'italic','link_close':'link'}[child.type],None); continue
                value = '\n' if child.type in ('softbreak','hardbreak') else child.content
                style = dict(active)
                if child.type == 'code_inline': style['weightedFontFamily'] = {'fontFamily':'Courier New'}
                if child.type == 'image': value = '[Image: ' + child.content + ']'
                offset = begin + utf16(content)
                if style and value: styles.append({'updateTextStyle':{'range':rng(offset,offset+utf16(value)), 'textStyle':style,'fields':','.join(style)}})
                content += value
        text += content + '\n'
        end = start + utf16(text)
        styles.append({'updateParagraphStyle':{'range':rng(begin,end),'paragraphStyle':{'namedStyleType':paragraph_style},'fields':'namedStyleType'}})
        if bullet:
            styles.append({'createParagraphBullets':{'range':rng(begin,end),'bulletPreset':'NUMBERED_DIGIT_ALPHA_ROMAN' if ordered else 'BULLET_DISC_CIRCLE_SQUARE'}})
        paragraph_style = 'NORMAL_TEXT'
    if not text: raise GdocsError('report section is empty')
    location = dict(index=start, **({'tabId':tab_id} if tab_id else {}))
    reset = {'updateTextStyle':{'range':rng(start,start+utf16(text)), 'textStyle':{}, 'fields':'bold,italic,link,weightedFontFamily'}}
    return [{'insertText':{'location':location,'text':text}}, reset, {'deleteParagraphBullets':{'range':rng(start,start+utf16(text))}}, *styles]

def section_range(document, heading):
    bodies = []
    def walk(tab):
        bodies.append((tab.get('tabProperties',{}).get('tabId'), tab.get('documentTab',{}).get('body',{})))
        for child in tab.get('childTabs',[]): walk(child)
    for tab in document.get('tabs',[]): walk(tab)
    if not bodies: bodies = [(None,document.get('body',{}))]
    matches = []
    for tab_id, body in bodies:
        content = body.get('content',[])
        for i, element in enumerate(content):
            p = element.get('paragraph',{}); style = p.get('paragraphStyle',{}).get('namedStyleType','')
            title = ''.join(e.get('textRun',{}).get('content','') for e in p.get('elements',[])).strip()
            if not style.startswith('HEADING_') or title.casefold() != heading.casefold(): continue
            end = content[-1]['endIndex'] - 1
            for following in content[i+1:]:
                next_style = following.get('paragraph',{}).get('paragraphStyle',{}).get('namedStyleType','')
                if next_style.startswith('HEADING_') and next_style <= style:
                    end = following['startIndex']; break
            matches.append((tab_id,element['endIndex'],end))
    if len(matches) != 1: raise GdocsError('section must match exactly one heading')
    return matches[0]

def update_section(target, heading, markdown, preview):
    from gdocs.drive_ops import open_drive, resolve
    from gdocs import services
    creds, drive = open_drive(write=not preview); meta = resolve(drive,'doc',target)
    docs = services.build('docs','v1',creds).documents()
    document = services.execute(docs.get(documentId=meta['id'],includeTabsContent=True))
    tab, start, end = section_range(document,heading)
    if start > end: raise GdocsError('add an empty paragraph below the section heading before updating it')
    requests = compile_section(markdown,start,tab)
    if end > start:
        requests.insert(0, {'deleteContentRange':{'range':dict(startIndex=start,endIndex=end, **({'tabId':tab} if tab else {}))}})
    if preview: return {'id':meta['id'],'section':heading,'markdown':markdown,'requests':requests,'preview':True}
    revision = document.get('revisionId')
    if not revision: raise GdocsError('document revision unavailable; refusing unguarded section update')
    services.execute(docs.batchUpdate(documentId=meta['id'],body={'requests':requests,'writeControl':{'requiredRevisionId':revision}}))
    return {'id':meta['id'],'section':heading,'updated':True}
