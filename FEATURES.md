# Work features

## Accessible reading

`gdocs config output plain` persists labeled, untruncated output. Explicit
`--output` overrides it. `gdocs doc read FILE --outline` lists headings;
`--section "Heading"` reads that heading and its subsections. Duplicate heading
names are refused. `gdocs sheet read FILE --tab TAB` reads labeled records.
