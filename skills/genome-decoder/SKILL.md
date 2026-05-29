---
name: genome-decoder
description: Re-audits a consumer DNA export's existing analysis documents into a deterministic, allow-list-cited, HelixyAI-branded HTML report. Use when the user wants to re-audit, rebuild, or verify a prior genome-analysis document set against their raw chip genotypes — e.g. "redo my genome report", "rebuild my health analysis from my 23andMe file", "verify what my prior genome docs claimed". It builds a genotype-truth INDEX from the raw export, audits the prior docs for unsupported or aspirational claims, rebuilds them with rsID + allow-list citations and a provenance block, and renders an interlinked HTML report. Requires a genome-reader install for parsing. Not a diagnostic tool — it restates authoritative-source guidance (CPIC/FDA/peer-reviewed) only and every recommendation ends with "consult your prescribing clinician".
---

# genome-decoder

An interpretation + audit pipeline that turns a consumer DNA export (23andMe /
AncestryDNA / MyHeritage) **plus an archive of prior analysis documents** into a
re-audited, evidence-graded, self-contained **HelixyAI HTML report**. It is the
second of two skills: it consumes `genome-reader` as a parsing substrate and adds
the interpretation, provenance, citation, and audit discipline on top.

**The binding contract is the SPEC**, bundled with the reference implementation at
`SPEC_genome_audit_workflow.md`. Where this file and the SPEC differ, the SPEC
wins. Read it before executing any phase.

## When to use

Trigger when the user wants to **re-audit / rebuild / verify** a genome-analysis
document set against their raw genotypes — for example:

- "re-audit my genome analysis" / "rebuild my health report from my raw DNA"
- "verify what my prior genome docs claimed against my chip data"
- "my old analysis has unsupported claims — redo it with citations"

The inputs are (1) a consumer DNA export and (2) a directory of prior analysis
documents to audit and rebuild.

## When not to use

This skill refuses, by design:

- **No diagnosis or prescription.** It restates CPIC / FDA / peer-reviewed
  guidance only; every clinical recommendation ends with "consult your
  prescribing clinician".
- **No parsing it can delegate.** Format detection, summary, rsID lookup, and
  VCF conversion go through `genome-reader` — this skill does not re-implement them.
- **No de novo assembly, alignment, or variant calling** (inherited boundary of
  the substrate).
- **No claim without evidence.** A clinical claim that lacks an INDEX-traceable
  rsID *and* an allow-list citation is deleted, not softened.

## Architecture: deterministic tools + an agent

genome-decoder is a **skill**, not a single script: deterministic Python tools do
the mechanical, reproducible work; the **agent** (you) does the interpretation,
routed through the gated write path. Scripts never author clinical prose.

- **Determinism is scoped to tool outputs** — the INDEX, the audit findings, the
  Phase-6 candidate set, and the rendered HTML are byte-deterministic for the same
  inputs + snapshot date. Agent-authored prose is **not** expected to be
  byte-reproducible and is not tested for it.

## Substrate: genome-reader (required)

All genome parsing delegates to a `genome-reader` install (≥ the `lookup.py
--columns` capability). Resolution: `$GENOME_READER_PATH`, else the sibling skill
`../genome-reader`. Operations used: `identify.py` (format/size), `summarize.py
--json` (snp_count / build / no-call rate), `lookup.py --columns
rsid,chrom,pos,genotype` (INDEX base rows), `convert.py --to vcf` (Phase-6
coordinate resolution; needs `fetch_assets.py` first). A missing/too-old substrate
stops the run with a clear message — no silent fallback.

## Workflow (8 phases, 0–7)

Each phase is atomic. Apply the **Non-Negotiable Rules** below and the SPEC's
`## Provenance Block Template` for every output document.

| Phase | What | Tooling |
|---|---|---|
| 0 | Spec, archive, **genotype-truth INDEX** | `index_build.py` (deterministic) ⏳ |
| 1 | Provenance & aspirational-claim **audit** (read-only) | `audit.py` (mechanical findings + *provisional* disposition; the agent decides + authors the report) ⏳ |
| 2 | Cross-doc corrections + provenance headers | `rebuild.py` (agent-authored, gated write) ⏳ |
| 3 | Pharmacogenomics rebuild | `rebuild.py` + allow-list fetch ⏳ |
| 4 | MTHFR / methylation expansion | `rebuild.py` ⏳ |
| 5 | Project-specific medical-context integration (a passed-in `<project_context>.md`) | `rebuild.py` ⏳ |
| 6 | Full net-new findings pass (ClinVar / ACMG SF / CPIC scan) | `discover.py` (candidate set only; the agent assigns tiers + resolves allele orientation) ⏳ |
| 7 | Executive summary, checkpoint, **final verification** | `verify.py` (runs the SPEC Verification Commands) ⏳ |

Output is rendered at each step against the HelixyAI templates.

### Rendering (present)

- `scripts/report_render.py` — generates the report **index** + each **document**
  by injecting structured content (`_common.ReportDocument` / `ReportManifest`)
  into the `HELIXY:*` seams of `assets/templates/{index,document}.html`. The
  templates are the single source of design truth (HelixyAI brand, helixyai.com).
- Every rendered document is **self-contained** (inline CSS/SVG, web-safe fonts,
  no network/CDN, print stylesheet) and honors the HTML contract: provenance as
  `<meta name="provenance:*">`, genomic data as `<code data-rsid data-chrom
  data-pos data-genotype>`, citations as `<a rel="external" data-access-date>`,
  semantic `<table>`.
- Writes go through `report_render.write_report_document` /
  `write_report_index`, which preserve the gates below.

## Non-Negotiable Rules (from the SPEC — enforced structurally)

1. **No aspirational claims.** A health/PGx claim must (a) cite an INDEX rsID with
   the subject's genotype, (b) cite an allow-list source, (c) be a current
   observation — never a future possibility. Forbidden tokens are in
   `assets/blacklist_phrases.txt`; the gate (`_common.assert_no_aspirational`)
   blocks the write. Aspirational tokens survive only inside archive-attributed
   `> [verbatim from archive: …]` blockquotes.
2. No claim carries forward without re-verification against the INDEX.
3. Reference assembly stated in every provenance block.
4. Every rsID citation includes chr:pos + genotype from the INDEX.
5. **No new dosing.** Restate authoritative guidance; end with "consult your
   prescribing clinician" (the renderer always emits the disclaimer).
6. Every output opens with a Provenance Block / Summary (missing ⇒ rejected).
7. Phase boundaries are atomic.
8. Citation access dates verified, not asserted.
9. **Never edit the archive** (immutable baseline; the renderer's archive guard
   refuses writes inside it).
10. Never run git in a non-git directory.

Allow-list citation sources (Evidence Sources): PubMed, ClinVar, CPIC, PharmGKB,
FDA Pharmacogenomic Biomarker Table, GWAS Catalog, dbSNP, gnomAD — encoded in
`assets/allowlist_sources.json`. A `Citation` cannot be constructed with an
off-list source.

## Privacy

The skill's **runtime output** carries the subject's real data and is written to a
local output directory — it is **never committed** to this repository and is not
obfuscated. Repository artifacts (this skill's code, tests, fixtures) use
**synthetic data only**. Do not place a real subject's export or output under
version control.

## Generalization

The pipeline is not subject-specific. Phase 5 ("project-specific medical context")
takes a passed-in `<project_context>.md` (timeline + checklist), not hardcoded
content. The Phase-3 pharmacogene list and Phase-4 methylation checklist are
general panels.

## Setup

    pip install -r requirements.txt   # pyyaml, requests, beautifulsoup4, pytest, pytest-mock

Tests are pure-Python and run without the substrate:

    python -m pytest tests/ -q

## Implementation status

Built incrementally. **Present:** the foundation (`scripts/_common.py` — types +
gates; `scripts/render.py` — legacy markdown/HTML), the structured report model,
and the HelixyAI renderer (`scripts/report_render.py`) + templates. **Pending
(⏳ above):** the deterministic phase tools `index_build.py`, `audit.py`,
`discover.py`, `rebuild.py`, `verify.py`. Until they land, the interpretive phases
are agent-driven against the SPEC, with the renderer producing the output.
