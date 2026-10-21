"""Exercise build/install routing without touching system tools or accounts."""
import json
import os
from pathlib import Path
import shutil
import subprocess

SOURCE = Path(__file__).resolve().parents[1] / 'build.sh'


def sandbox(tmp_path):
    root = tmp_path / 'checkout with spaces'; root.mkdir()
    shutil.copy2(SOURCE,root/'build.sh')
    log=tmp_path/'calls.jsonl'
    fake=tmp_path/'fake-uv'
    fake.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
with open(os.environ['BUILD_TEST_LOG'],'a') as f:
    f.write(json.dumps({'args':sys.argv[1:],'cwd':os.getcwd(),'bin':os.environ.get('UV_TOOL_BIN_DIR'),'tools':os.environ.get('UV_TOOL_DIR')})+'\\n')
if sys.argv[1] == 'build':
    Path('dist/gdocs-0.1.0-py3-none-any.whl').touch()
''')
    fake.chmod(0o755)
    env=dict(os.environ,UV=str(fake),BUILD_TEST_LOG=str(log))
    return root,log,env


def invoke(root,env,*args):
    return subprocess.run([str(root/'build.sh'),*args],cwd=root.parent,env=env,text=True,capture_output=True)


def test_help_and_bad_arguments_do_not_run_uv(tmp_path):
    root,log,env=sandbox(tmp_path)
    assert invoke(root,env,'help').returncode == 0
    assert invoke(root,env,'unknown').returncode == 2
    assert invoke(root,env,'install','prefix=relative').returncode == 2
    assert not log.exists()


def test_install_and_update_use_isolated_prefix_and_constraints(tmp_path):
    root,log,env=sandbox(tmp_path)
    prefix=tmp_path/'installed tools'
    for target in ('install','update'):
        result=invoke(root,env,target,f'prefix={prefix}')
        assert result.returncode == 0,result.stderr
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    assert all(c['cwd'] == str(root) for c in calls)
    installs=[c for c in calls if c['args'][:2] == ['tool','install']]
    assert len(installs) == 2
    assert installs[0]['bin'] == str(prefix/'bin')
    assert installs[0]['tools'] == str(prefix/'lib/gdocs-tools')
    assert '--constraints' in installs[0]['args']
    assert '--reinstall-package' in installs[1]['args']


def test_tests_use_locked_dev_dependencies(tmp_path):
    root,log,env=sandbox(tmp_path)
    assert invoke(root,env,'test').returncode == 0
    calls=[json.loads(line)['args'] for line in log.read_text().splitlines()]
    assert calls[0] == ['sync','--locked','--extra','dev']
    assert calls[1][-3:] == ['python','-m','pytest']


def test_clean_preserves_environment_and_rejects_symlink(tmp_path):
    root,log,env=sandbox(tmp_path)
    (root/'.venv').mkdir(); (root/'dist').mkdir(); (root/'dist/artifact').touch()
    assert invoke(root,env,'clean').returncode == 0
    assert (root/'.venv').exists() and not (root/'dist').exists()
    outside=tmp_path/'outside'; outside.mkdir(); (outside/'keep').touch()
    (root/'dist').symlink_to(outside,target_is_directory=True)
    assert invoke(root,env,'clean').returncode == 2
    assert (outside/'keep').exists()
