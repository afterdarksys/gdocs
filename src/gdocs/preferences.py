"""Small persistent user preferences, separate from credentials."""
import json
from gdocs.auth import config_dir
from gdocs.filesafe import atomic_write, prepare_output, read_text_input

def load():
    path = config_dir() / 'preferences.json'
    return json.loads(read_text_input(str(path), 1048576)) if path.exists() else {}

def save(data):
    path = config_dir() / 'preferences.json'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    prepare_output(path, force=True)
    atomic_write(path, lambda f: f.write((json.dumps(data, indent=2)+'\n').encode()))
