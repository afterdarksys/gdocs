"""Bounded HTTPS diagnostics with pinned origin, no redirects, and secret redaction."""
from dataclasses import dataclass, field
import base64
from http.client import HTTPException
import json
import os
import re
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from gdocs.errors import GdocsError
from gdocs.redact import redact

MAX_RESPONSE = 5 * 1024 * 1024
SAFE_HEADERS = ('content-type','retry-after','x-arequestid','atl-traceid','x-request-id',
                'x-ratelimit-limit','x-ratelimit-remaining','x-ratelimit-reset','ratelimit-reason')
SECRET_KEYS = {'authorization','proxyauthorization','cookie','setcookie','password','secret',
               'clientsecret','token','accesstoken','refreshtoken','apitoken','apikey'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_base(value):
    if not isinstance(value,str) or any(ord(c) < 33 for c in value):
        raise GdocsError('Jira URL must be a valid HTTPS base URL')
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise GdocsError('Jira URL must use HTTPS without credentials, query, or fragment')
    try: parsed.port
    except ValueError: raise GdocsError('invalid Jira URL port') from None
    if '\\' in value or '%' in parsed.path or any(p in ('.','..') for p in parsed.path.split('/')):
        raise GdocsError('invalid Jira base path')
    return value.rstrip('/')


def scrub(value, secrets=()):
    if isinstance(value,dict):
        return {scrub(str(key),secrets):('[redacted]' if re.sub(r'[^a-z]','',str(key).lower()) in SECRET_KEYS else scrub(item,secrets)) for key,item in value.items()}
    if isinstance(value,list): return [scrub(item,secrets) for item in value]
    if isinstance(value,str):
        for secret in sorted((s for s in secrets if s),key=len,reverse=True): value=value.replace(secret,'[redacted]')
        value = re.sub(r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9+/_.=-]+',r'\1 [redacted]',value)
        return redact(value)
    return value


def diagnosis(status):
    if 200 <= status < 300: return 'Request succeeded.'
    if 300 <= status < 400: return 'Redirect refused. Check the Jira base URL, context path, and SSO/proxy routing.'
    return {
        400:'Jira rejected the parameters or JQL; inspect the returned validation errors.',
        401:'Authentication failed. Check token expiry, identity, deployment type, and Cloud scoped-token routing.',
        403:'Access denied. Check account access, token scopes, project permissions, and organization policy.',
        404:'Resource unavailable: it may be missing, hidden by permissions, or addressed through the wrong API/base URL.',
        405:'This endpoint does not support GET; this diagnostic client does not execute write methods.',
        429:'Rate limited. Inspect Retry-After and rate-limit headers; this client does not automatically retry.',
    }.get(status,'Jira or its proxy returned an error; use the request ID to correlate server logs.')


@dataclass
class Client:
    base: str
    authorization: str = field(repr=False)
    secret: str = field(repr=False)
    timeout: int = 20
    opener: object = None

    def __post_init__(self):
        self.base = validate_base(self.base)
        if not 1 <= self.timeout <= 120: raise GdocsError('timeout must be between 1 and 120 seconds')
        if self.opener is None:
            try: context = ssl.create_default_context(cafile=os.environ.get('JIRA_CA_BUNDLE'))
            except (OSError,ssl.SSLError): raise GdocsError('could not load Jira CA bundle') from None
            self.opener = build_opener(HTTPSHandler(context=context),NoRedirect())

    def get(self,path,params=None):
        if not re.fullmatch(r'/rest/api/[23]/[A-Za-z0-9_./~-]+',path) or '//' in path or any(p in ('.','..') for p in path.split('/')):
            raise GdocsError('request path must stay under /rest/api/2/ or /rest/api/3/ without query strings or traversal')
        params = params or {}
        if any(re.sub(r'[^a-z]','',key.lower()) in SECRET_KEYS for key in params):
            raise GdocsError('credentials must not be sent in query parameters')
        url = self.base + path + ('?' + urlencode(params,doseq=True) if params else '')
        request = Request(url,headers={'Authorization':self.authorization,'Accept':'application/json','User-Agent':'gdocs-jira-debug/0.1'},method='GET')
        start=time.monotonic()
        trace={'method':'GET','path':path,'queryKeys':sorted(params)}
        try:
            try: response=self.opener.open(request,timeout=self.timeout)
            except HTTPError as exc: response=exc
            with response:
                status=response.status
                headers={k:response.headers[k] for k in SAFE_HEADERS if response.headers.get(k) is not None}
                body=response.read(MAX_RESPONSE+1)
        except (URLError,OSError,TimeoutError,HTTPException) as exc:
            reason=getattr(exc,'reason',exc)
            kind='tls' if isinstance(reason,ssl.SSLError) else ('timeout' if isinstance(reason,TimeoutError) else 'connection')
            return {'ok':False,'status':None,'errorType':kind,'diagnosis':{
                'tls':'TLS verification failed. Check the hostname, certificate chain, and JIRA_CA_BUNDLE.',
                'timeout':'Request timed out; check connectivity or increase --timeout.',
                'connection':'Connection failed; check DNS, VPN, proxy configuration, and Jira availability.'}[kind],
                'trace':trace,'elapsedMs':round((time.monotonic()-start)*1000)}
        secrets=(self.secret,self.authorization,self.authorization.partition(' ')[2])
        result={'ok':200 <= status < 300,'status':status,'diagnosis':diagnosis(status),
                'trace':trace,'headers':headers,'elapsedMs':round((time.monotonic()-start)*1000)}
        if len(body) > MAX_RESPONSE:
            result.update(ok=False,errorType='response-too-large',diagnosis='Response exceeds 5 MiB; request fewer fields or results.')
        else:
            try: result['data']=json.loads(body) if body else None
            except (ValueError,UnicodeError):
                result.update(ok=False,errorType='non-json',diagnosis=diagnosis(status)+' Expected JSON but received another format; check SSO interception and reverse-proxy routing. Response body omitted.')
        return scrub(result,secrets)


def authorization(deployment,email,token):
    if not token or len(token) > 16384 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise GdocsError('Jira token is missing or invalid; set the documented environment variable')
    if deployment == 'cloud':
        if not email or ':' in email or any(ord(c) < 33 for c in email): raise GdocsError('Cloud authentication requires an account email')
        encoded=base64.b64encode((email+':'+token).encode()).decode()
        return 'Basic '+encoded
    return 'Bearer '+token
