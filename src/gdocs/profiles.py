"""Account selection independent of per-account credentials and preferences."""
import hashlib
import json
import os
from pathlib import Path
import re
from gdocs.errors import GdocsError
from gdocs.filesafe import atomic_write, prepare_output, read_text_input


def root():
    return Path(os.environ.get('GDOCS_CONFIG_DIR', Path.home() / '.config' / 'gdocs'))


def registry():
    path = root() / 'profiles.json'
    return json.loads(read_text_input(str(path), 1048576)) if path.exists() else {'active': 'default', 'profiles': {}}


def save(data):
    path = root() / 'profiles.json'
    prepare_output(path, force=True)
    atomic_write(path, lambda f: f.write(json.dumps(data, indent=2).encode()))


def selected():
    data = registry()
    name = os.environ.get('GDOCS_PROFILE') or data.get('active', 'default')
    if name != 'default' and name not in data['profiles']:
        raise GdocsError(f'unknown profile: {name}')
    return name


def directory():
    name = selected()
    return root() if name == 'default' else root() / 'profiles' / name


def keyring_account():
    name = selected()
    if name == 'default': return 'default'
    digest = hashlib.sha256(str(root().absolute()).encode()).hexdigest()[:16]
    return f'{digest}:{name}'


def create(name, email=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', name) or name == 'default':
        raise GdocsError('profile name must be 1–80 letters, digits, underscores or hyphens, excluding default')
    data = registry()
    if name in data['profiles']: raise GdocsError('profile already exists')
    if email and ('@' not in email or any(c.isspace() for c in email)):
        raise GdocsError('expected account must be an email address')
    data['profiles'][name] = {'expectedEmail': email}
    save(data)
    return {'profile': name, 'expectedEmail': email, 'next': f'GDOCS_PROFILE={name} gdocs login --client CLIENT.json'}


def use(name):
    data = registry()
    if name != 'default' and name not in data['profiles']: raise GdocsError('unknown profile')
    data['active'] = name
    save(data)
    return {'selected': selected(), 'savedDefault': name}


def listing():
    data = registry()
    return [{'profile': name, 'active': name == selected(), **values}
            for name, values in {'default': {}, **data['profiles']}.items()]


def write_context(drive):
    """Check the actual account before any write under a named profile."""
    name = selected()
    if name == 'default': return
    from gdocs import services
    from gdocs.workspaces import active
    from gdocs.redact import redact
    import sys
    user = services.execute(drive.about().get(fields='user(emailAddress)')).get('user', {})
    email = user.get('emailAddress', '')
    expected = registry()['profiles'][name].get('expectedEmail')
    if expected and email.casefold() != expected.casefold():
        raise GdocsError('authenticated account differs from profile expectedEmail; refusing write', 4)
    workspace, _ = active()
    print(redact(json.dumps({'writeContext': {'profile': name, 'account': email, 'workspace': workspace}})), file=sys.stderr)
