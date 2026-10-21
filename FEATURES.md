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
