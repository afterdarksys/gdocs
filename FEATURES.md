# Work features

## Accessible reading

`gdocs config output plain` persists labeled, untruncated output. Explicit
`--output` overrides it. `gdocs doc read FILE --outline` lists headings;
`--section "Heading"` reads that heading and its subsections. Duplicate heading
names are refused. `gdocs sheet read FILE --tab TAB` reads labeled records.

## Change reviews

`gdocs snapshot FILE --name last-review` saves a private local baseline.
`gdocs changes FILE --since last-review [--summary]` compares document headings.
For sheets, pass `--kind sheet --tab TAB --key finding_id` to both commands.
Without a key, sheet comparisons use row positions. Snapshots include retrieved
content (including formulas for sheets); protect the config directory accordingly.
Review does not advance a baseline; run snapshot explicitly after reviewing.

## Review comments

`gdocs comments list FILE --unresolved --output plain` includes author, quoted
context when supplied by Google, and replies. Use `comments add FILE "text"`,
`comments reply FILE COMMENT_ID "text"`, or `comments resolve FILE COMMENT_ID`.
`--kind sheet|present` selects other file types. New comments are file-level:
Drive API anchors are not rendered as native inline anchors in Google editors.

## Finding upserts

`gdocs sheet upsert FILE --key finding_id --columns severity,last_seen,evidence
--json findings.json --tab Findings --preview` shows individual cell changes.
Omit `--preview` to apply. Input is an array of objects; keys must be nonempty
strings. Only declared columns may appear besides the key. Missing fields stay
unchanged; empty strings clear cells. Other columns, including formulas, survive.
Reruns update existing keys rather than appending duplicates. A second read detects
changes during planning, but Sheets has no compare-and-swap here: serialize
writers to this tab to avoid a race between the final read and write.

## Report templates and Markdown

`gdocs report render security-weekly --data results.json --name "Weekly security"
--preview` renders Markdown and HTML locally. Remove preview to publish a Google
Doc with headings, lists, links, tables and code formatting via HTML conversion.
Built-ins: `security-weekly`, `threat-model`, `incident`, `architecture-review`.
A template can also be a Markdown path. Placeholders use `{{field}}`; missing data
fails, and inserted data is Markdown (not executable template code). Raw HTML is
escaped. Inspect built-in fields with `src/gdocs/reports.py`.

Use `--into FILE --section "Automation results"` instead of `--name` to replace
only the content under one existing heading, including its subsections. Other
sections and the selected heading remain intact. Section writes use a revision
precondition and support headings, lists, emphasis, links and code. Tables are
supported for new reports but explicitly refused in section updates. Preview
section updates reads the document but does not write. Nested list indentation
and image embedding are not preserved in section updates; image alt text remains.

## CI execution

Set `GDOCS_CI=1` for JSON runtime errors on stderr and disabled interactive login.
Use `GDOCS_AUTH=adc` for Application Default Credentials, including workload
identity configurations through `GOOGLE_APPLICATION_CREDENTIALS`. The identity
must have access to the files. Otherwise existing saved OAuth credentials work.
Exit codes: 1 general failure, 2 argument error, 3 conflict/uncertain replay,
4 authentication/permission failure, 5 transient API failure, 130 interruption.
Argument-parser errors retain standard argparse text. No writes are auto-retried.

`gdocs run --id pipeline-123-report --receipt receipt.json -- doc create --name Report`
records an operation in the private config directory. Repeating the same ID and
arguments replays the saved result without writing again. Changed arguments fail.
An interrupted/failed operation stays uncertain and requires checking remote state
before deliberately choosing a new ID. Persist the config directory between CI
jobs; deduplication is local, not distributed. Receipts contain command results,
which can include document contents. `run --preview` validates arguments only;
use upsert/report previews for actual planned remote edits. Docs replace/append
and report section updates now require the revision observed before the write.

## Evidence packages

`gdocs evidence collect ./evidence-123 --source doc:FILE --source sheet:FILE
--ticket SEC-123 --control AC-2` exports DOCX/XLSX/PPTX files into a new directory,
with a manifest of source IDs, versions, links, timestamps, byte lengths and SHA-256
hashes. Collection fails if source metadata changes during an export. Sources are
collected sequentially, not as a transaction. Partial packages are removed.
`gdocs evidence verify ./evidence-123` detects missing or altered exported files.
The manifest is unsigned: hashes verify integrity relative to it, not provenance.

## Workspaces and aliases

```
gdocs workspace create security --folder FOLDER_ID_OR_URL
gdocs workspace use security
gdocs alias set incident-runbook DOCUMENT_ID
gdocs alias set risk-register SHEET_ID --kind sheet
gdocs doc read incident-runbook --section Containment
gdocs workspace recent --limit 10
```

Aliases are verified when set and checked for file type when used. `@alias` forces
alias interpretation; bare aliases also work. List/remove with `gdocs alias list`
and `gdocs alias remove NAME`. `workspace list` shows available workspaces;
`workspace use none` disables scoping. `GDOCS_WORKSPACE=NAME` overrides the saved
selection for a process. Lists, searches, and exact-name lookups are scoped to
immediate children of the workspace folder (not recursive descendants). IDs,
URLs and aliases still address their explicit files. This is a navigation scope,
not an authorization boundary. Creating files does not move them into the folder.

## Account profiles

`gdocs profile create work --email engineer@example.com` creates isolated settings.
`gdocs profile use work` selects it; then run the normal OAuth login. Use
`GDOCS_PROFILE=work gdocs ...` to select a profile explicitly in a script.
`profile list` shows selection. `profile use default` restores the original token,
keychain entry, aliases and settings without migration. Named profiles isolate
OAuth keychain entries, fallback token files, workspaces, snapshots and operations.
An optional expected email is verified against Drive before named-profile writes;
the account, profile and workspace are printed to stderr before writing. ADC is
still selected by the process environment; profiles do not change its identity.

## Folders and shared drives

`gdocs drives` lists accessible shared drives and capabilities. Use a shared-drive
root ID or any folder ID with `workspace create ... --folder ID`.
`gdocs folder list [FOLDER] --recursive` lists descendants; `folder pwd` shows the
workspace's current folder. `folder cd FOLDER_ID_OR_URL` changes that workspace's
folder, and `folder cd ..` goes to its accessible parent. Aliases remain unchanged.
`gdocs doc search "risk" --recursive` (also list/find for every editor type) searches
all descendant folders of the active workspace, bounded to 1000 folders; shortcuts
are not followed. Results are sorted globally by modification time before limiting.
Incomplete API search results fail explicitly. Shared-drive folder searches use the
specific drive corpus, with pagination.

`gdocs folder create "Evidence" [--parent FOLDER]` creates a folder. New editor
files, imports, and reports now use the active workspace folder and require its
`canAddChildren` capability. Without a workspace they retain My Drive defaults.
`gdocs folder move FILE --kind doc --to FOLDER --preview` previews a move; omit
preview to apply. `--kind sheet|present|folder` selects other types. Moves check
capabilities; folder cycles and cross-drive folder moves are refused. Google's
permissions and organization policies remain authoritative for moves.

## Review inbox and suggestion previews

`gdocs inbox --output plain` scans the 50 most recently modified Docs, Sheets and
Slides within the current scope, showing unreviewed/changed files and unresolved
comments. Use `--kind doc`, `--limit 100`, `--recursive`, `--details` (comment threads
and content diffs), or `--all` (include clear items). The result reports truncation
and per-file comment/read errors, so failed scans do not appear clear. This is a
bounded polling inbox, not a server-side assignment or notification feed.

After reading, `gdocs review mark FILE` explicitly acknowledges the current remote
version locally and refreshes its `last-review` snapshot. It does not resolve
comments. For sheets use `--kind sheet --tab Findings --key finding_id`; content
comparisons cover that tab while modification status is file-wide. Slides use
metadata acknowledgement. Each profile has independent review state.

`gdocs doc suggestions FILE --view current|proposed|changes` provides read-only
views of the text without suggestions, text with all suggestions hypothetically
accepted, or heading-level differences plus suggestion metadata (including style
suggestions). Views are labeled and revision mismatches fail. Ordinary document
reads now explicitly exclude suggestions; index-based writes use inline suggestion
indexes. Suggestion acceptance/rejection is not performed by these commands.

## CI recovery and retention

`gdocs operations list --status started` finds uncertain operations.
`gdocs operations inspect OPERATION_ID` shows status, context, errors and results.
After independently checking remote state, record your conclusion with either:

```
gdocs operations reconcile JOB --outcome completed --result verified-result.json --note "Verified document ID against the job output"
gdocs operations reconcile JOB --outcome not-applied --note "Verified no document was created"
```

These commands record an operator assertion, not an automatic remote verification.
They never rerun a write. Completed reconciliation requires a JSON result for future
replays; not-applied reconciliation keeps the old ID reserved and requires a new ID
for an intentional retry. Active operations hold an OS file lock, preventing concurrent
execution, reconciliation, or compaction. Operation fingerprints now bind arguments
to profile, workspace/aliases and authentication configuration. Older journals without
that context remain inspectable but are not replayed automatically.

`gdocs retention prune --snapshots-days 30 --receipts-days 30 --operations-days 90`
previews changes; add `--apply` to execute. Snapshots expire by collection timestamp.
Managed receipts under the active profile expire by completion/reconciliation time;
external receipt exports and evidence packages are untouched. Completed operations
are compacted to archived records retaining their ID, fingerprint and completion time.
Their result payloads are removed; rerunning an archived ID fails without executing.
Uncertain and not-applied operations, credentials, review acknowledgements, and lock
files are retained. Locked or concurrently changed state is skipped. Keep operation
records on persistent local storage; this is not a distributed execution lock.
