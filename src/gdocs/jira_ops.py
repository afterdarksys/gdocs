"""Read-only Jira troubleshooting using profile-local non-secret settings."""
import os
import re
from gdocs.errors import GdocsError
from gdocs.preferences import load, save
from gdocs.jira_http import Client, authorization, validate_base

PERMISSIONS = 'BROWSE_PROJECTS,CREATE_ISSUES,EDIT_ISSUES,TRANSITION_ISSUES'


class DiagnosticResult(dict):
    @property
    def exit_code(self):
        if self.get('ok',True): return 0
        statuses = [self.get('status')] + [item.get('status') for item in self.get('checks',[])]
        if any(s in (401,403) for s in statuses): return 4
        if any(s in (429,500,502,503,504) for s in statuses) or self.get('errorType') in ('connection','timeout') or any(item.get('errorType') in ('connection','timeout') for item in self.get('checks',[])):
            return 5
        return 1


def configure(url,deployment='cloud',email=None,cloud_id=None,token_env=None):
    settings={'url':validate_base(url),'deployment':deployment,'email':email,'cloudId':cloud_id,
              'tokenEnv':token_env or ('JIRA_API_TOKEN' if deployment == 'cloud' else 'JIRA_PAT')}
    validate_settings(settings)
    data=load(); data['jira']=settings; save(data)
    return {'saved':True,**settings,'note':'Only non-secret settings saved. Supply the token through the named environment variable.'}


def validate_settings(settings):
    if settings.get('deployment') not in ('cloud','datacenter'): raise GdocsError('deployment must be cloud or datacenter')
    settings['url']=validate_base(settings.get('url',''))
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',settings.get('tokenEnv','')): raise GdocsError('invalid token environment variable name')
    cloud_id=settings.get('cloudId')
    if cloud_id and (settings['deployment'] != 'cloud' or not re.fullmatch(r'[A-Za-z0-9-]{1,128}',cloud_id)):
        raise GdocsError('cloud ID must be an ID for a Cloud deployment')
    if settings['deployment'] == 'cloud' and not settings.get('email'): raise GdocsError('Cloud configuration requires --email or JIRA_EMAIL')
    return settings


def settings():
    config=dict(load().get('jira',{}))
    for env,key in [('JIRA_URL','url'),('JIRA_DEPLOYMENT','deployment'),('JIRA_EMAIL','email'),('JIRA_CLOUD_ID','cloudId'),('JIRA_TOKEN_ENV','tokenEnv')]:
        if env in os.environ: config[key]=os.environ[env]
    config.setdefault('deployment','cloud')
    config.setdefault('tokenEnv','JIRA_API_TOKEN' if config['deployment'] == 'cloud' else 'JIRA_PAT')
    return validate_settings(config)


def status():
    config=settings()
    return {**config,'tokenPresent':bool(os.environ.get(config['tokenEnv'])),'authentication':'email + API token' if config['deployment']=='cloud' else 'personal access token (Bearer)'}


def connect(timeout=20):
    config=settings()
    token=os.environ.get(config['tokenEnv'],'')
    if not token: raise GdocsError(f"set {config['tokenEnv']} before running Jira diagnostics",4)
    base = 'https://api.atlassian.com/ex/jira/'+config['cloudId'] if config.get('cloudId') else config['url']
    client=Client(base,authorization(config['deployment'],config.get('email'),token),token,timeout)
    return client, '/rest/api/' + ('3' if config['deployment']=='cloud' else '2'), config


def identifier(value,label='identifier'):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value): raise GdocsError(f'invalid Jira {label}')
    return value


def permission_params(project=None,issue=None,permissions=PERMISSIONS):
    if not permissions or not all(re.fullmatch(r'[A-Z][A-Z_]*',p) for p in permissions.split(',')):
        raise GdocsError('permissions must be comma-separated Jira permission keys')
    params={'permissions':permissions}
    if project: params['projectKey']=identifier(project,'project key')
    if issue: params['issueKey']=identifier(issue,'issue key')
    return params


def doctor(project=None,issue=None,timeout=20):
    params=permission_params(project,issue)
    client,api,config=connect(timeout)
    requests=[('server',api+'/serverInfo',{}),('identity',api+'/myself',{}),('permissions',api+'/mypermissions',params)]
    if project: requests.append(('project',api+'/project/'+identifier(project),{}))
    if issue: requests.append(('issue',api+'/issue/'+identifier(issue),{'fields':'summary,status,project'}))
    checks=[{'check':name,**client.get(path,params)} for name,path,params in requests]
    return DiagnosticResult(ok=all(row['ok'] for row in checks),deployment=config['deployment'],checks=checks,
                            note='Successful permissions requests can contain havePermission=false; inspect the individual permission values.')


def inspect_resource(action,target=None,project=None,issue=None,permissions=PERMISSIONS,timeout=20):
    params={}
    if action == 'permissions':
        params=permission_params(project,issue,permissions); resource='/mypermissions'
    elif action == 'fields': resource='/field'
    elif action == 'project': resource='/project/'+identifier(target,'project key')
    elif action == 'issue':
        resource='/issue/'+identifier(target,'issue key'); params={'fields':'summary,status,project,issuetype,assignee','expand':'names,schema'}
    elif action == 'transitions':
        resource='/issue/'+identifier(target,'issue key')+'/transitions'; params={'expand':'transitions.fields'}
    else: raise GdocsError('unknown Jira diagnostic action')
    client,api,_=connect(timeout)
    return DiagnosticResult(client.get(api+resource,params))


def request(path,parameters,timeout=20):
    params={}
    for item in parameters:
        key,sep,value=item.partition('=')
        if not sep or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',key): raise GdocsError('parameters must be KEY=VALUE')
        if key in params: raise GdocsError('duplicate query parameter')
        params[key]=value
    client,_,_=connect(timeout)
    return DiagnosticResult(client.get(path,params))


def search(jql,limit=50,timeout=20):
    if not jql or len(jql)>10000: raise GdocsError('JQL must contain 1–10000 characters')
    if not 1<=limit<=1000: raise GdocsError('search limit must be between 1 and 1000')
    client,api,config=connect(timeout)
    cloud=config['deployment']=='cloud'
    path=api+('/search/jql' if cloud else '/search')
    issues=[]; checks=[]; token=None; offset=0; seen=set(); more=False
    while len(issues)<limit:
        params={'jql':jql,'maxResults':min(100,limit-len(issues)),'fields':'summary,status,project,issuetype'}
        if cloud and token: params['nextPageToken']=token
        if not cloud: params['startAt']=offset
        page=client.get(path,params)
        checks.append({k:v for k,v in page.items() if k != 'data'})
        if not page['ok']:
            return DiagnosticResult(ok=False,status=page['status'],checks=checks,issues=issues,error=page.get('data'),partial=bool(issues))
        data=page.get('data')
        if not isinstance(data,dict) or not isinstance(data.get('issues'),list):
            return DiagnosticResult(ok=False,checks=checks,issues=issues,diagnosis='Unexpected Jira search response shape.',partial=bool(issues))
        batch=data['issues']; issues.extend(batch[:limit-len(issues)])
        if cloud:
            token=data.get('nextPageToken'); more=bool(token)
            if data.get('isLast') is True: more=False
            if not more: break
            if token in seen: raise GdocsError('Jira repeated a search cursor; refusing an endless pagination loop')
            seen.add(token)
        else:
            offset+=len(batch)
            total=data.get('total')
            more=isinstance(total,int) and offset<total
            if not more: break
        if not batch: raise GdocsError('Jira returned an empty page while indicating more results')
    return DiagnosticResult(ok=True,issues=issues,count=len(issues),truncated=more,checks=checks)
