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
