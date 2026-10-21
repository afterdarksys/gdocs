# Jira API diagnostics

These commands inspect Jira through GET requests. They do not create/edit issues,
execute transitions, or change permissions. Tests use mocked responses; live Jira
behavior has not been verified against your instance.

## Configure an account

Settings are isolated by the selected gdocs profile. Only the URL, deployment type,
email, optional Cloud ID and token environment variable name are stored locally.
Jira credentials are separate from Google OAuth credentials.

For Jira Cloud with a classic API token:

```sh
gdocs jira configure --url https://your-team.atlassian.net --email you@example.com
# Supply JIRA_API_TOKEN through your shell's secret prompt or CI secret injection.
gdocs jira status --output plain
gdocs jira doctor --project SEC --output plain
```

For a scoped Cloud API token, add `--cloud-id YOUR_CLOUD_ID` to configure. Requests
then use `https://api.atlassian.com/ex/jira/YOUR_CLOUD_ID`. Cloud authentication uses
the account email plus API token; it does not implement an OAuth consent flow.

For Jira Data Center with a personal access token:

```sh
gdocs jira configure --deployment datacenter --url https://jira.example.com/jira
# Supply JIRA_PAT through your secret manager or environment.
gdocs jira doctor --issue SEC-123 --output plain
```

Data Center uses Bearer authentication. Context paths such as `/jira` are preserved.
`--token-env WORK_JIRA_TOKEN` chooses another environment variable name, useful when
separate profiles need separate secrets. `status` reports whether the token is
present without contacting Jira or displaying it.

Environment overrides: `JIRA_URL`, `JIRA_DEPLOYMENT`, `JIRA_EMAIL`, `JIRA_CLOUD_ID`,
and `JIRA_TOKEN_ENV`. Deployment values are `cloud` and `datacenter`. Prefer distinct
profiles rather than overriding deployment type on a configured Cloud profile.
All requests verify HTTPS certificates. For an internal CA, set `JIRA_CA_BUNDLE`
to your trusted PEM bundle. Standard urllib proxy environment settings are honored.

## Troubleshoot

```sh
gdocs jira doctor --project SEC --issue SEC-123 --output plain
gdocs jira permissions --issue SEC-123 --permissions BROWSE_PROJECTS,EDIT_ISSUES --output json
gdocs jira project SEC --output plain
gdocs jira issue SEC-123 --output plain
gdocs jira transitions SEC-123 --output plain
gdocs jira fields --output json
gdocs jira search 'project = SEC AND statusCategory != Done' --limit 100 --output json
gdocs jira request /rest/api/3/issue/SEC-123/editmeta --output json
gdocs jira request /rest/api/3/issue/SEC-123 --param fields=summary,status --timeout 30 --output plain
```

Use `/rest/api/2/...` for raw Data Center requests. Generic requests are GET-only
and restricted to `/rest/api/2/` or `/rest/api/3/` on the configured base. Full URLs,
path traversal, redirects, and credential query parameters are refused.

`doctor` checks server information, identity and permissions, plus optional project
and issue access. HTTP success on a permissions endpoint does not mean every
permission is granted: inspect individual `havePermission` values. A 404 cannot
distinguish a nonexistent issue from one hidden by permissions. Scoped tokens may
lack access to particular diagnostics even when other requests work.

Search paginates up to `--limit` (1–1000). Cloud uses `/search/jql` with
`nextPageToken`; Data Center uses `/search` with `startAt`. Results indicate truncation
and preserve partial results if a later request fails. Transitions include available
transition fields; they are never executed.

## Output and failures

Responses include HTTP status, elapsed time, query parameter **names**, request IDs,
and allowlisted content-type/rate-limit headers. No request authorization headers,
query values, cookies or HTML response bodies are logged. Known credentials and
common secret fields are redacted from returned JSON. Issue content and personal
information may still be present: this is not a comprehensive data-loss-prevention
filter. Treat captured responses as work data.

HTTP and transport failures return nonzero exits while preserving structured
results on stdout: 4 for authentication/permission failures, 5 for transient API
failures, 1 for other failures. Configuration/argument errors follow the normal CLI
error handling. `--output plain` provides untruncated labeled fields; JSON is useful
for CI. Timeout defaults to 20 seconds per request (range 1–120); no automatic
retries occur. Responses are bounded to 5 MiB per request. Run Jira diagnostics
directly: the journaled `gdocs run` wrapper refuses them to avoid replaying stale
diagnostic results.

References:
- [Cloud API-token authentication](https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/)
- [Scoped-token gateway authentication](https://support.atlassian.com/atlassian-cloud/kb/401-unauthorized-error-when-service-account-accesses-jira-or-confluence-api/)
- [Cloud issue search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/)
- [Data Center personal access tokens](https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html)
