from gdocs.output import render, choose_output
from gdocs import reading
import pytest
from gdocs.errors import GdocsError

def test_plain_preserves_full_values():
    value = 'asset-' + 'x'*100
    assert value in render([{'Asset': value, 'Owner': 'Ryan'}], 'plain')
    assert 'Owner: Ryan' in render([{'Owner': 'Ryan'}], 'plain')

def test_section_boundaries(monkeypatch):
    from gdocs import doc_ops
    monkeypatch.setattr(doc_ops, 'view', lambda *a, **k: '# Start\na\n## Child\nb\n# End\nc')
    assert reading.read('id', 'Start') == '# Start\na\n## Child\nb'
    with pytest.raises(GdocsError): reading.read('id', 'missing')

def test_preferences(tmp_path, monkeypatch):
    monkeypatch.setenv('GDOCS_CONFIG_DIR', str(tmp_path))
    from gdocs.preferences import save
    save({'output': 'plain'})
    assert choose_output(None, True) == 'plain'
    assert choose_output('json', True) == 'json'
