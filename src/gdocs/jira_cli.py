"""Jira diagnostics CLI; credentials are never command-line arguments."""
from gdocs.work_cli import leaf


def register(nouns,common):
    root=nouns.add_parser('jira',help='read-only Jira API diagnostics')
    verbs=root.add_subparsers(dest='jira_action',required=True)
    p=leaf(verbs,'configure',common,dispatch)
    p.add_argument('--url',required=True); p.add_argument('--deployment',choices=['cloud','datacenter'],default='cloud')
    p.add_argument('--email'); p.add_argument('--cloud-id'); p.add_argument('--token-env')
    leaf(verbs,'status',common,dispatch)
    for name in ('doctor','permissions','project','issue','transitions','fields','search','request'):
        p=leaf(verbs,name,common,dispatch)
        p.add_argument('--timeout',type=int,default=20)
        if name in ('doctor','permissions'):
            p.add_argument('--project'); p.add_argument('--issue')
        if name == 'permissions': p.add_argument('--permissions',default='BROWSE_PROJECTS,CREATE_ISSUES,EDIT_ISSUES,TRANSITION_ISSUES')
        if name in ('project','issue','transitions'): p.add_argument('target')
        if name == 'search': p.add_argument('jql')
        if name == 'request':
            p.add_argument('path'); p.add_argument('--param',action='append',default=[])


def dispatch(a):
    from gdocs import jira_ops as jira
    action=a.jira_action
    if action == 'configure': return jira.configure(a.url,a.deployment,a.email,a.cloud_id,a.token_env)
    if action == 'status': return jira.status()
    if action == 'doctor': return jira.doctor(a.project,a.issue,a.timeout)
    if action == 'search': return jira.search(a.jql,a.limit if a.limit is not None else 50,a.timeout)
    if action == 'request': return jira.request(a.path,a.param,a.timeout)
    return jira.inspect_resource(action,getattr(a,'target',None),getattr(a,'project',None),getattr(a,'issue',None),getattr(a,'permissions',jira.PERMISSIONS),a.timeout)
