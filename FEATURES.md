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
