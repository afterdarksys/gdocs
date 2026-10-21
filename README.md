# gdocs

Command line for Google Docs, Sheets, and Slides. Listing, search, sharing, tags, import, and export go through Drive. Docs, Sheets, and Slides handle the file contents.

## Setup

To run directly from this checkout:

```bash
uv sync
./bin/gdocs setup
# Or sign in with an existing Desktop OAuth client:
./bin/gdocs login --client ~/Downloads/client_secret.json
./bin/gdocs status
```

`bin/gdocs` uses the checkout's `.venv` when available, or the current
`python3` environment otherwise (install the project dependencies there first).
It works from any directory and through a symlink, while resolving command
arguments such as client-file paths relative to your current directory.
OAuth login opens your browser for consent; add `--readonly` for read-only
access. Saved credentials are reused and refreshed by subsequent commands.

Install from this checkout as a CLI tool, then run the setup wizard:

```bash
uv tool install --editable .
uv tool update-shell
# Restart your shell if uv updated PATH.
gdocs setup
```

`gdocs` is then available from any directory without activating a virtual
environment. The editable install picks up changes in this checkout; keep the
checkout in place. For development only, `uv sync --extra dev` and
`uv run gdocs <command>` also work.

The wizard prompts through project creation, enabling the Drive, Docs, Sheets,
and Slides APIs, consent-screen configuration, and downloading a Desktop OAuth
client. It validates the file, asks whether to use read-only access, and opens
Google sign-in. Cloud project configuration is completed in your browser; the
wizard provides links and waits after each step. See Google's
[credential setup guide](https://developers.google.com/workspace/guides/create-credentials).

Already have a client file? Run `gdocs setup --client ~/Downloads/client_secret.json`.
Add `--readonly` to request read-only access without the access-mode question.
For login without terminal prompts, use
`gdocs login --client ~/Downloads/client_secret.json` (browser consent still applies).

A refresh token from an app that is still in testing expires after 7 days. Publishing the consent screen to Production keeps the token for personal use. Google then shows an unverified-app warning because the Drive scope is restricted. That warning is expected for a personal desktop client.

`gdocs login --readonly` requests `https://www.googleapis.com/auth/drive.readonly`. A normal login requests `https://www.googleapis.com/auth/drive`. Writes need the full Drive scope.

The refresh token is stored in the macOS keychain under the service name `gdocs`. If the keychain cannot store it, the fallback is `~/.config/gdocs/token.json` with mode `0600`. `gdocs logout` deletes whichever copy is stored. `gdocs status` prints the account email, the granted scopes, where the token lives, and when the access token expires. The email comes from Drive, not from a separate userinfo call.

## Commands

`doc` is also `docs`. `sheet` is also `sheets`. `present` is also `presents` and `slides`. A target may be a file id, a Google editor URL, or a file name that matches one file of that type.

Every command accepts `--output table|json|ndjson|csv`. A terminal defaults to a table. Any other stdout defaults to JSON.

```bash
gdocs doc list --query budget --tag q1 --starred
gdocs doc view FILE --format md
gdocs doc search "renewal date"
gdocs doc edit FILE replace OLD NEW
gdocs doc edit FILE append "a note"
gdocs doc tag FILE add q1 client:acme
gdocs doc tag FILE list
gdocs doc share FILE user:ada@example.com writer
gdocs doc share FILE anyone reader --yes
gdocs doc export FILE pdf ./out.pdf
gdocs doc import notes.md --name Notes

gdocs sheet view FILE --tab Leads --head 20
gdocs sheet update FILE "Leads!A2:C2" --values '[["Ada","acme","open"]]'
gdocs sheet update FILE --tab Leads --append --json ./rows.json
gdocs sheet edit-cell FILE --cell F2 --value won
gdocs sheet edit-cell FILE --cell F2 --formula '=D2*E2'
gdocs sheet edit-row FILE --where 'email=ada@example.com' --set status=won
gdocs sheet edit-col FILE --col status --from G
gdocs sheet filter FILE --where 'status=open AND amount>1000'
gdocs sheet extract FILE --cols name,email,amount --output json
gdocs sheet json FILE
gdocs sheet import book.xlsx --name Book
gdocs sheet import rows.csv --into FILE --tab Leads --replace

gdocs present edit FILE replace OLD NEW
gdocs present edit FILE add-slide --title Title --body "Slide text"
gdocs present export FILE pptx ./deck.pptx

gdocs doc create --name Notes
gdocs doc create --name Notes --text "First paragraph"
gdocs sheet create --name Leads --columns name,email,phone
gdocs sheet create --name Leads --columns name,email,phone --values '{"name":"Ryan","email":"ryan@foo.com","phone":"55555555"}'
gdocs sheet update FILE --tab Leads --append --values '{"name":"Ada","email":"ada@example.com","phone":"555"}'
gdocs sheet import rows.json --name Leads
gdocs present create --name Deck
gdocs present create --name Deck --deck deck.yaml
gdocs present edit FILE set-slide --slide 1 --title Hello --body "Slide text" --notes "Say this"
gdocs present edit FILE add-slide --title Title --body "Slide text" --notes "Say this"
gdocs present import deck.yaml --name Deck
gdocs present export FILE yaml ./deck.yaml
gdocs convert notes.docx ./notes.pdf
gdocs convert notes.pdf ./notes.docx --keep
```

`find` matches the file name. `search` matches the body, then prints a short local snippet.

Deleting a row or a column, and sharing with `anyone`, require `--yes`.

## Import, export, and tags

Docs export as pdf, docx, txt, html, or md. Sheets export as xlsx, csv, pdf, or ods. Slides export as pptx, pdf, or txt. An existing destination is refused unless you pass `--force`.

Import creates a new Google file by uploading through Drive. A Markdown file is uploaded as plain text and converted to a Google Doc. This tool does not parse Markdown.

`gdocs sheet import rows.csv --into FILE --replace` parses the CSV locally and replaces one tab in a spreadsheet that already exists. `--replace` is required with `--into`. An `.xlsx` import always creates a new spreadsheet. `gdocs sheet import rows.json --name Leads` creates a new spreadsheet from JSON records. JSON with `--into` is refused.

`gdocs convert IN OUT` imports through Drive and exports another format. Docs convert among docx, md, txt, html, and pdf. Sheets convert among csv, xlsx, pdf, and ods. Slides convert among pptx, pdf, and txt. The same suffix is refused. The intermediate Google file is trashed unless you pass `--keep`. If that trash fails, the command still exits 0 and the result includes the leftover file id.

A PDF import is real but lossy. Drive embeds the PDF in a Doc. Text in a later docx or txt export is whatever Drive extracted. docx to pdf is the clean path. ods stays export-only.

`gdocs sheet create` writes values as RAW, so a phone number and `=1+1` stay literal. Formulas go through `sheet update --formula`. `--tab` renames the first sheet after the values are written.

`gdocs present import` and `present export json|yaml|yml` use a local slide deck, not a Drive export. The write shape is a title plus slides of title, body, and notes. An all-digit slide id is a 1-based index. Export is lossy for layouts that are not title and body. JSON and YAML are slide decks, not convert pairs.

Tags live in the Drive file property `gdocs_tags`. They are not Workspace labels. Each tag is stored between commas, so a search for `q1` does not match `q10`.

Header row 1 is the schema for `sheet json`, `extract`, `--where`, and `--col name`. A column letter also works. An exact header wins when a header and a letter would both match.
