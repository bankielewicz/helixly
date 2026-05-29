# genome-decoder assets

Provenance for every bundled asset, and the substrate version pin.

## Substrate version pin (genome-reader)

genome-decoder shells out to `genome-reader` for all genome-parsing operations
(SPEC "Phase 7 Amendment"). genome-reader exposes no `--version`, so we pin by
**capability**: the minimum requirement is the presence of

    lookup.py --columns rsid,chrom,pos,genotype

which projects `rsid · chromosome · position · genotype` from the consumer-DNA
substrate. Phase 0 INDEX construction depends on it (it supplies the chr:pos
columns the SPEC's `lookup.py rsid<TAB>genotype` v1 output lacked).

- **Minimum genome-reader commit:** `862e6ab791a6dc96771583ed42497144ed1bd461`
  ("feat(lookup): add --columns flag for rsid/chrom/pos/genotype projection").
- **Resolution order for the substrate path:** `$GENOME_READER_PATH`, else the
  sibling skill directory `../genome-reader`.
- **Interpreter:** genome-reader's own `.venv` if present, else the current
  Python. `_common.run_substrate` is the single chokepoint; a missing or
  too-old substrate stops the run with the message in
  `_common.substrate_version_note()`.

Verified output shapes (captured 2026-05-28 against genome-reader's own
fixtures; matches SPEC validation table, SPEC lines 462–468):

| substrate call | output |
|---|---|
| `identify.py <p>` | `{"format": "consumer_dna:23andme", "size_bytes": int, ...}` |
| `summarize.py <p> --json` | `{"format", "snp_count": int, "build": "GRCh37"\|"GRCh38", "chromosome_distribution": {...}, "no_call_rate": float}` |
| `lookup.py <p> --rsids <pool> --columns rsid,chrom,pos,genotype` | TSV, header `rsid<TAB>chrom<TAB>pos<TAB>genotype`; present rows `rs1<TAB>1<TAB>100<TAB>AG`; absent rows `rsX<TAB><TAB><TAB>not_tested` |

## blacklist_phrases.txt

Faithful copy of the SPEC's Aspirational Phrase Blacklist token list (SPEC
"Appendix: Aspirational Phrase Blacklist"), one ERE alternative per line.
Compiled case-insensitively by `_common._load_blacklist_patterns()`. The
exemptions (archive-attributed blockquotes, Glossary/Appendix, code spans, the
stable `likely-pathogenic`/`likely-benign` classes) live in
`_common.find_blacklist_hits`, not in this file — keep the list a faithful copy
of the SPEC tokens.

## allowlist_sources.json

The citation allow-list registry — the eight sources of SPEC "Evidence
Sources", keyed by short source name, each with its identifier format and a URL
template. `_common.fetch_allowed` rejects any source key not present here
(`AllowlistError`); there is no code path that fetches an off-list URL. Add new
allow-listed sources here, not in code.

## Allow-list cache (generated at run time, not bundled)

Network fetches are cached under `<output_dir>/.allowlist_cache/<source>/` with
content-addressed filenames `<identifier>_<YYYYMMDD>.<ext>` where the date is
the **snapshot date** (an explicit `--snapshot-date` input, not the wall clock).
Re-running on the same snapshot date is offline and byte-identical — this is the
determinism contract of SPEC line 370. The cache directory *is* the access-date
ledger; the renderer reads each citation's access date back off the filename.
This directory is run-output, not a bundled asset, and is `.gitignore`d.

## templates/index.html — HelixyAI report index template

The canonical HTML template for the **report index / landing hub** of the
interlinked output (SPEC "Output Format"; the report is a set of ~24 documents
plus this index). It is the design source of truth for the output's look — the
renderer generates the live index against this template's structure and styling;
it is not served as-is.

Provenance: produced by Claude Design (claude.ai/design) for the **HelixyAI**
brand (helixyai.com), exported as a handoff bundle, placed here verbatim. It is
**self-contained** — all CSS inline, web-safe fonts, inline SVG logo, vanilla JS,
no network/CDN, with a print stylesheet — and uses **synthetic data only**
("Sample Subject", invented rsIDs/SHAs). It honors the SPEC HTML contract:
`<meta name="provenance:*">` in `<head>`, genomic data as
`<code data-rsid data-chrom data-pos data-genotype>`, citations as
`<a rel="external" data-access-date>`, semantic `<table>`.

Design system (apply across all rendered docs): palette navy `#143049` ·
scientific teal `#2f7d6b` · warm clay `#a9572a` (Tier 1 / alerts) on warm paper
`#f6f5f0`; Georgia headlines · system-sans body · monospace for all genomic data;
persistent grouped sidebar + breadcrumb + prev/next pager; tier badges (1/2/3).

The matching **per-document** template (provenance card, provider-alert table,
finding blocks with code-chip triples, genotype table, historical blockquotes,
clinician disclaimer) is the representative `Pharmacogenomics Analysis.html` from
the same design bundle — to be added when the renderer's per-doc HTML path
(Workstream D2) is built.
