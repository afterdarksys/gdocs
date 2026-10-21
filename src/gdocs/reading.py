"""Linear reading and unambiguous heading navigation."""
import re
from gdocs.errors import GdocsError

def sections(text):
    lines = text.splitlines()
    result = []
    for i, line in enumerate(lines):
        match = re.match(r'^(#{1,6}) (.+)$', line)
        if match:
            result.append({'heading': match[2], 'level': len(match[1]), 'line': i})
    return result

def read(target, section=None, outline=False):
    from gdocs.doc_ops import view
    text = view(target, fmt='md')
    headings = sections(text)
    if outline:
        return [{'heading': h['heading'], 'level': h['level']} for h in headings]
    if not section:
        return text
    matches = [h for h in headings if h['heading'].casefold() == section.casefold()]
    if len(matches) != 1:
        raise GdocsError('section must match exactly one heading')
    h = matches[0]
    end = next((x['line'] for x in headings if x['line'] > h['line'] and x['level'] <= h['level']), len(text.splitlines()))
    return '\n'.join(text.splitlines()[h['line']:end])
