---
spec_id: genome-audit-workflow
spec_title: Phased Genome Audit Workflow
spec_version: 1.1
spec_packaging: genericized-bundle
spec_provenance_note: |
  This is the genome-decoder skill's bundled copy of the binding contract. It is
  the SAME contract (v1.1) as the reference implementation it was derived from,
  with all subject-identifying data removed and replaced by synthetic
  placeholders. It is a SANITIZED copy, not a new contract: the phases, rules,
  evidence sources, blacklist, templates, and verification commands are
  unchanged. Subject genome hashes, genotypes, counts, medical history, real
  filesystem paths, usernames, and repository identifiers have been genericized.
  Per-run subject data is written into the private (gitignored) output directory
  at Phase 0 — never into this file or any repository artifact.
spec_extracted_from: <master plan path>
spec_extracted_on: 2026-05-26
spec_amended_on: 2026-05-26
spec_amendment_summary: Phase 6 INDEX-extension semantics locked; Cross-Reference Syntax section added; Aspirational Phrase Blacklist appendix added with stable-terminology exemption; Phase 7 verification adds blacklist grep; two-skill build path documented (genome-reader first, then genome-decoder).
spec_phase_7_amendment_on: 2026-05-28
spec_phase_7_amendment_summary: |
  genome-reader substrate integration. Every genome-parsing PowerShell snippet
  in this SPEC is amended to show the equivalent genome-reader invocation as
  the primary form, with PowerShell (or sha256sum/grep equivalents) retained as
  fallback. Non-genome-parsing operations (SHA-256, filesystem `ls`, markdown
  grep) are NOT amended — they remain PowerShell/bash because genome-reader
  does not cover those operations. One genome-reader v1 gap is documented:
  `lookup.py` historically output `rsid<TAB>genotype` only; the INDEX schema
  requires `rsid <TAB> chromosome <TAB> position <TAB> genotype`. The
  `lookup.py --columns rsid,chrom,pos,genotype` extension closes the gap inside
  genome-reader; `genome-decoder` Phase 0 consumes it directly.
spec_phase_7_amendment_substrate_path: $GENOME_READER_PATH (else sibling skill ../genome-reader)
spec_phase_7_amendment_validation: |
  The genome-reader substrate is validated, not asserted: each run confirms the
  substrate against ITS OWN source genome before relying on it. See
  `## Phase 7 Amendment — genome-reader Substrate Integration` →
  `### Substrate validation procedure (run per audit)`. No recorded historical
  PASS is carried in this bundled contract — the substrate is re-validated
  against the live subject's file each time.
spec_extracted_by_model: <model id, e.g., claude-opus-4-x[1m]>
spec_supersedes: SPEC_genome_audit_workflow.md v1.0 (extracted 2026-05-26 morning); v1.0 had no INDEX-extension semantics, no blacklist appendix, no cross-reference syntax, single-skill packaging.
spec_intended_consumer: the genome-decoder skill (this skill)
spec_reference_implementation: a synthetic reference fixture; per-run output lives in the private output directory
spec_substrate_skill: genome-reader (parsing/conversion/lookup operations delegate to it)
output_format_intermediate: markdown
output_format_final: HTML (self-contained single-file HelixyAI report)
edit_strategy: archive-and-replace
phase_total: 8
phase_numbering: 0-through-7
---

# SPEC — Phased Genome Audit Workflow (v1.1)

This SPEC is the deterministic encoding of the workflow that re-audits a
prior-model-generated genome documentation set against the actual raw genome
file. It is the **binding contract** for the `genome-decoder` skill: where the
skill's `SKILL.md` and this SPEC differ, **this SPEC wins**. Read it before
executing any phase.

> **Bundled, sanitized copy.** This file is the genome-decoder skill's bundled
> contract. It is the same v1.1 contract as the reference implementation it was
> derived from, with every subject-identifying value replaced by a synthetic
> placeholder (see `spec_provenance_note` in the frontmatter). The skill is
> self-contained: it does not depend on any subject's private archive to obtain
> this contract. Real subject data is produced only at runtime, into the
> private (gitignored) output directory.

`genome-decoder` consumes `genome-reader` as a substrate for parsing operations.
See `## /skill-creator Follow-On` for the two-skill split.

---

## Non-Negotiable Rules

These rules apply to every phase.

1. **Operational definition of "aspirational claim."** A health, dietary, supplement, or pharmacogenomic claim is **aspirational** if it fails any one of the following three tests:
   - (a) Cites a specific rsid that exists in `INDEX_genotype_truth.tsv` with the subject's observed genotype. The INDEX is initialized in Phase 0 (rsids cited in v1 docs) and extended in Phase 6 (rsids discovered in the full-genome net-new pass). Each row carries a `discovered_in_phase` column (`0` or `6`) recording its origin.
   - (b) Cites at least one resolvable external source from the allow-list in `## Evidence Sources`.
   - (c) Is phrased as a current observation about the subject's genotype, not as a future possibility. Forbidden phrasings are enumerated in `## Appendix: Aspirational Phrase Blacklist`. The blacklist is enforced by grep.
   - Any aspirational claim is **deleted** in the rebuild, not softened, not flagged, not commented out. Aspirational tokens are permitted only inside verbatim quotes from archive docs (clearly demarcated with markdown blockquote `>` and an inline `[verbatim from archive\<archive_dir>\<filename>]` attribution).
2. **No claim carries forward without re-verification** against `INDEX_genotype_truth.tsv`. Presence of a claim in a prior-model doc is not evidence of its correctness.
3. **Reference assembly is declared by the genome file's header** (typically GRCh37/hg19 for 23andMe exports from 2024). Every replacement doc states this in its provenance block.
4. **Every rsid citation includes chr:pos and the subject's genotype** at first mention in each doc, copied from `INDEX_genotype_truth.tsv` — not re-derived ad hoc.
5. **No new dosing prescriptions.** Recommendations restate authoritative-source guidance (CPIC, FDA, peer-reviewed clinical guidelines) only. Every clinical recommendation ends with "consult your prescribing clinician."
6. **Every output file opens with a Provenance Block** (template below). Missing block = file rejected.
7. **Phase boundaries are atomic.** A phase is "done" only when (a) all deliverables exist on disk, (b) `CHANGELOG.md` records each one, (c) `## Status` in the master plan is updated, (d) the next phase's continuation prompt exists at the configured prompts directory. Partial-phase carryovers require an explicit `in_flight_files` list in `## Status` AND a CHANGELOG entry naming the in-flight files.
8. **Citation access dates are verified, not asserted.** Any URL recorded as a citation must be confirmed reachable by the session writing it (using WebFetch). If the URL does not resolve on the day of writing, the identifier alone is recorded and the citation is marked `url_verified: false`.
9. **Never edit a file under the archive directory.** It is the immutable historical baseline.
10. **Never use git commands in directories that are not git repositories.** The skill must detect git presence before any git operation.

---

## Edit Strategy: Archive-and-Replace (locked)

**Pattern.**
1. Phase 0 moves every prior-model doc into `<output_dir>\archive\v1_<prior_model_id>\` with original filename preserved (single move event, per-file SHA-256 in CHANGELOG).
2. The new replacement lives at the **original path**.
3. Until a doc is replaced by its phase, the archived copy is the read-only reference.
4. `CHANGELOG.md` is the per-phase event log; one entry per phase completion.

**Rejected alternatives.**
- *Edit-in-place* destroys the baseline.
- *Append-only amendments* leave prior errors readable as if current.
- *Per-doc hybrid* requires per-file judgment a generalized skill cannot encode.

---

## Cross-Reference Syntax

All cross-document references inside canonical docs use this exact form:

```markdown
[<doc-id> §<section-name>](./<filename>#<anchor-slug>)
```

Example: `[doc 09 §Codeine](./09_PGX_Analysis.md#codeine)`.

Rationale: relative markdown links survive HTML rendering (genome-decoder's output format), are parser-deterministic, and produce a clickable navigation graph.

Rules:
- Always relative (`./<filename>`), never absolute paths in cross-references.
- Always link to canonical paths, never to archive paths (archive references go in a doc's "Historical context" appendix as plain text, not as cross-references).
- Plain-text mentions of another doc in prose do not count as cross-references and do not satisfy a Phase-N deliverable that calls for cross-referencing another phase's output.
- Anchor slugs follow GitHub-flavored-markdown lowercase-hyphen rules: heading "## Codeine Reclassification" → anchor `codeine-reclassification`.

---

## Reference Assembly & Genome File

The skill records, in Phase 0:
- Absolute path of the source genome file.
- **SHA-256** via `Get-FileHash -Algorithm SHA256` (PowerShell) or `sha256sum` (bash). NOT a genome-reader operation per the Phase 7 amendment — genome-reader does not compute hashes; keep PowerShell / bash hash commands.
- **Byte count** via `Get-Item -Length` / `wc -c` (PowerShell / bash); equivalently `identify.py` returns `size_bytes`.
- **Data-row count + chromosome distribution + reference assembly** via `genome-reader summarize.py <source_genome_path> --json`. The JSON output's `snp_count` field is the number of SNP data rows (excluding header comments); `build` is the assembly (`GRCh37` or `GRCh38`); `chromosome_distribution` is the per-chromosome row count; `no_call_rate` is the fraction of `--` genotype calls. **This replaces the prior `(Get-Content … | Measure-Object -Line).Lines` PowerShell snippet** per the Phase 7 amendment. The total file line count (data rows + header comments) remains available via PowerShell `Measure-Object -Line` or bash `wc -l` if needed.
- **Provider** parsed from header comments — `identify.py` returns `consumer_dna:23andme` / `consumer_dna:ancestrydna` / `consumer_dna:myheritage` for consumer DNA exports.
- **File-generation timestamp** parsed from header comments — NOT a genome-reader-exposed field; bash / PowerShell `head -20` extracts the header block.
- **Column layout** parsed from column-header row — for consumer DNA, the layout is fixed per provider (23andMe: `rsid <TAB> chromosome <TAB> position <TAB> genotype`); genome-reader's `iter_consumer_dna` substrate (in `_common.py`) handles parsing transparently.

Values are written into the master plan frontmatter AND every Provenance Block. Drift between recorded values and the live file at later phases is a STOP condition.

---

## Evidence Sources (citation allow-list)

| Source | Identifier format | Canonical URL root |
|---|---|---|
| PubMed | `PMID: 17634449` | https://pubmed.ncbi.nlm.nih.gov/{PMID}/ |
| ClinVar | `ClinVar VCV000017692` or `RCV...` | https://www.ncbi.nlm.nih.gov/clinvar/variation/{VCV_numeric}/ |
| CPIC guideline | `CPIC {gene} guideline` | https://cpicpgx.org/guidelines/ |
| PharmGKB | `PharmGKB {gene/variant ID}` | https://www.pharmgkb.org/ |
| FDA Pharmacogenomic Biomarker Table | `FDA PGx Biomarker Table` | https://www.fda.gov/drugs/science-and-research-drugs/table-pharmacogenomic-biomarkers-drug-labeling |
| GWAS Catalog | `GWAS Catalog accession GCST...` | https://www.ebi.ac.uk/gwas/ |
| dbSNP (rsid metadata only) | `rs1801133` | https://www.ncbi.nlm.nih.gov/snp/{rsid} |
| gnomAD (allele frequency only) | `gnomAD v4` | https://gnomad.broadinstitute.org/ |

Sources NOT in the allow-list cannot back a clinical claim on their own.

---

## Provenance Block Template

```yaml
---
doc_id: <filename without extension>
produced_by: <model id, e.g., claude-opus-4-x[1m]>
produced_on: <YYYY-MM-DD>
phase: <0-7>
source_genome_path: <absolute path>
source_genome_sha256: <SHA-256 from Phase 0>
source_genome_assembly: <GRCh37 | GRCh38 | other>
source_genome_line_count_verified: <integer>
genotype_index_path: <absolute path to INDEX_genotype_truth.tsv>
genotype_index_sha256: <SHA-256 of INDEX at the time this doc was written>
supersedes: <absolute path of archived predecessor>
supersedes_sha256: <SHA-256 of the archived predecessor>
removed_claims_count: <integer>
added_claims_count: <integer>
external_sources_used: [PubMed, ClinVar, CPIC, PharmGKB, FDA, GWAS_Catalog, dbSNP, gnomAD]
external_sources_access_date: <YYYY-MM-DD>
---

## Provenance Summary

**Supersedes.** `<archive path>` (SHA-256 above).

**Removed claims** (verbatim quote → reason removed):
- "<verbatim quote from v1>" → reason: <unsupported by genome.txt | no allow-list citation | aspirational phrasing | contradicts INDEX>

**Added claims** (one-line summary):
- <rsid> <chr:pos> <subject genotype> → <clinical implication> [<citation>]
```

---

## Continuation Prompt Template

```markdown
# Phase {N} Continuation Prompt — Genome Audit

You are resuming a phased genome audit with NO prior conversational context.
Check for work-in-flight on disk before assuming a clean state; see In-Flight Recovery.

## Mandatory startup sequence

1. Read in full: <master plan path>
2. Read: <changelog path> (if missing, you are pre-Phase-0)
3. Read the plan's `## Status` block. Confirm `last_completed_phase` equals {N-1}.
   - If > {N-1}: STOP. Phase already done.
   - If < {N-1}: STOP. Prior phase incomplete.
   - If `in_flight_files` non-empty: see `## In-Flight Recovery`.
4. List the contents of the output directory and its archive subdirectory.
   Confirm filesystem state matches CHANGELOG. If not, STOP.

## Execute Phase {N}

Find `## Phase {N}` in the plan. Execute exactly the deliverables listed there.
Apply `## Non-Negotiable Rules`. Use `## Provenance Block Template` for every output.

## On completion

1. Update `## Status` in plan.
2. Append a CHANGELOG entry under `## Phase {N}`.
3. Write `<prompts_dir>\phase{N+1}_prompt.md` from this template.
4. STOP. Report to user.

## In-Flight Recovery

Partial replacement doc (Provenance Block present, body incomplete, no CHANGELOG entry):
1. Move to `<archive>\inflight_<YYYYMMDD_HHMMSS>_<filename>`.
2. Record the move in CHANGELOG.
3. Restart the deliverable from scratch.

## Hard stops

- Never edit archive files (except `inflight_*` per recovery).
- Never make clinical claims without an INDEX-traceable rsid AND allow-list citation.
- Never use git in non-git-repo directories.
- If genome SHA-256 in plan frontmatter does not match live SHA-256, STOP.
```

---

## Phase 0 — Spec, Archive, Genotype-Truth Index

**Deliverables.**
1. Source genome SHA-256 recorded in plan frontmatter, CHANGELOG, and Phase 0 entry.
2. Archive directory created; all prior-model docs moved into it with per-file SHA-256 recorded.
3. `CHANGELOG.md` new file with `## Phase 0` entry.
4. `SPEC_genome_audit_workflow.md` (this file) extracted from the master plan.
5. `INDEX_genotype_truth.tsv` deterministic extract (every rsid in any archived doc looked up in source genome). Initial schema: `rsid <TAB> chromosome <TAB> position <TAB> genotype <TAB> found <TAB> source_docs`. PowerShell or Python only — no LLM interpretation. Per the Phase 7 amendment: delegate to `genome-reader lookup.py <source_genome_path> --rsids <pool> --columns rsid,chrom,pos,genotype` for the per-rsid `rsid + chrom + pos + genotype` lookup. The `--columns` flag was added to the substrate per this Phase 7 amendment's original wishlist; the legacy awk bridge is no longer required for new callers. The `found` and `source_docs` columns are added by `genome-decoder` after the substrate-driven join. The `discovered_in_phase` column is added in Phase 6 (initial backfill `0` for Phase-0 rows; Phase-6 additions stamped `6`; reference-implementation also used `4` and `5` for Phase-4 / Phase-5 checklist-scoped INDEX extensions — record per-phase origin in the column).
6. `INDEX_genotype_truth.md` human-readable companion.
7. `phase1_prompt.md` in prompts directory.
8. Master plan `## Status` block updated.

---

## Phase 1 — Provenance & Aspirational-Claim Audit (READ-ONLY)

**Deliverables.**
1. `REPORT_phase1_audit.md` with one `## <archived filename>` section per archived doc, listing per claim: missing rsid linkage, missing allow-list citation, aspirational phrasing (against the Blacklist), rsid absent from INDEX, internal contradictions, rebuild recommendation (`delete` / `rewrite-with-citation` / `keep-as-is`), and project-specific corrections to propagate.
2. CHANGELOG updated, master plan `## Status` updated, `phase2_prompt.md` written.

---

## Phase 2 — Cross-Doc Corrections & Provenance Headers

**Deliverables.** Replacement files at canonical paths for every non-rebuild doc (Phases 3–6 handle their own rebuilds). Each replacement opens with a Provenance Block; applies Phase 1's `delete` and `rewrite-with-citation` directives; propagates project-specific corrections. **No net-new analytical claims in Phase 2.** CHANGELOG/Status/`phase3_prompt.md` updates.

---

## Phase 3 — Pharmacogenomics (PGX) Rebuild

**Deliverables.**

1. Replacement PGX doc at canonical path. In-scope pharmacogene list is fixed: CYP2D6, CYP2C19, CYP2C9, CYP1A2, CYP3A4, CYP3A5, VKORC1, TPMT, NUDT15, NAT2, UGT1A1, SLCO1B1, DPYD. For each gene on this list, if at least one defining-variant rsid is in INDEX with `found = y`: defining rsids with subject's genotype from INDEX; metabolizer phenotype call with citation to CPIC/PharmGKB; affected drugs with FDA/CPIC dosing-guidance reference.
2. Provider-ready alert card at the head of the doc — CPIC Level A findings only.
3. Any project-specific drug reclassification (e.g., codeine = metabolism issue not allergy) reflected consistent with the corresponding Phase 2 rewrite.
4. CHANGELOG/Status/`phase4_prompt.md` updates.

---

## Phase 4 — MTHFR & Methylation Pathway Expansion

**Deliverables.**

1. Replacement MTHFR doc. In-scope rsid checklist is fixed:
   - **MTHFR.** rs1801133 (C677T), rs1801131 (A1298C).
   - **MTR.** rs1805087 (A2756G).
   - **MTRR.** rs1801394 (A66G).
   - **CBS.** rs5742905, rs234706.
   - **BHMT.** rs3733890.
   - **AHCY.** rs819147.
   - **SHMT1.** rs1979277.
   - **MAT1A.** rs17421511.
   - **TYMS.** rs502396.

   For every rsid: if INDEX `found = y`, analyze in detail; if `found = n`, record under "Chip coverage gaps." Methylation-pathway rsids in INDEX but not on this checklist are out of Phase 4 scope (reserved for Phase 6).

2. Reconciled replacement of any related methylation-analysis doc — no genotype contradictions for shared rsids.
3. Project-specific medical-context integration where allow-list literature supports.
4. CHANGELOG/Status/`phase5_prompt.md` updates.

---

## Phase 5 — Project-Specific Medical Context Integration

**Deliverables.**

1. Replacement medical-notes doc. The subject's surgical/medical timeline is preserved verbatim from the archive; genetic interpretations are rebuilt with INDEX + allow-list rigor. Open-ended items (for example, an unresolved post-procedure symptom whose etiology was never established) are preserved as open, not resolved by inference.
2. New context-specific dedicated doc. The in-scope rsid checklist is a fixed, general panel keyed to the categories the passed-in `<project_context>.md` raises. The illustrative panel below is **synthetic example structure**, not a real subject's findings:
   - **Bile-acid recycling.** ABCB11 rs2287622. NR1H4 rs56163822. ABCB4 rs2230028.
   - **Fat-soluble vitamin (A/D/E/K) absorption.** GC rs2282679. NPC1L1 rs2072183. APOA5 rs662799.
   - **NSAID metabolism, peri-operative.** NAT2 rs1799929, rs1799930, rs1799931, rs1208 (cross-reference per `## Cross-Reference Syntax` to the canonical PGX doc).
   - **Opioid metabolism, peri-operative.** CYP2D6 defining rsids (cross-reference to PGX doc).
   - **Methylation recovery, peri-operative.** MTHFR rs1801133, rs1801131 (cross-reference to MTHFR doc).

   For every rsid: if INDEX `found = y`, integrate in detail; if `found = n`, record under "Chip coverage gaps." The category set is driven by the passed-in project context; it is not hardcoded to any one subject.

3. CHANGELOG/Status/`phase6_prompt.md` updates.

---

## Phase 6 — Full 1M-Context Net-New Findings Pass

**Deliverables.**

1. **Extended `INDEX_genotype_truth.tsv`** (in-place edit; locked decision):
   - **Schema change.** New column `discovered_in_phase` (`0` for Phase-0 rows, `6` for Phase-6 additions). Phase-0 backfill is part of this deliverable.
   - **New rows.** Any rsid identified during Phase 6 scan with `found = y` AND referenced by an allow-list source (ClinVar pathogenic/likely-pathogenic; ACMG SF v3 reportable gene; CPIC Level A or B drug-gene pair) is appended with `discovered_in_phase = 6` and `source_docs = phase6_discovery`.
   - **Hash recording.** Pre-extension SHA-256 recorded in CHANGELOG before edit; post-extension SHA-256 recorded after. Master plan frontmatter preserves `genotype_index_sha256_phase0` and adds `genotype_index_sha256_phase6`.

2. **Replacement flagship comprehensive doc.** Incorporates Phases 2–5 by cross-reference; adds findings supported by extended INDEX; every claim passes aspirational-claim test.

3. **New net-new-findings doc.** Each finding records: rsid, chr:pos, subject's genotype, allow-list citation with `url_verified` field, clinical-significance tier (1/2/3), `discovered_in_phase` value, AND a grep-verification block:

   ```text
   Verification: Grep tool pattern="rs1234567" glob="<archive flagship path>" output_mode="count"
   Expected result: 0
   Observed result: 0
   ```

4. CHANGELOG/Status/`phase7_prompt.md` updates.

### Phase 6 Scan Procedure (deterministic)

A. **ClinVar pass.** Fetch ClinVar variant summary for pathogenic and likely-pathogenic variants (URL recorded with access date). For each variant: if rsid exists in source genome data rows AND subject's genotype matches the pathogenic allele state, add to candidate set.

B. **ACMG SF v3 pass.** For each gene on the ACMG SF v3 reportable list, identify the gene's coordinate range. For each source-genome row whose chromosome + position falls within a reportable gene's range AND whose rsid is annotated pathogenic in ClinVar with the subject's matching allele state, add to candidate set.

C. **CPIC Level A/B pass.** For each drug-gene pair at CPIC Level A or B, identify defining rsids; for each rsid present in the source genome not already in the Phase-0 INDEX, add to candidate set.

D. **Dedup.** Union the three candidate sets. Drop any rsid already in Phase-0 INDEX. The remaining set is the Phase-6 extension.

E. **Write.** Append extension rows to `INDEX_genotype_truth.tsv` after backfilling `discovered_in_phase` on Phase-0 rows.

---

## Phase 7 — Executive Summary, Checkpoint Refresh, Final Verification

**Deliverables.**

1. Replacement analysis-plan doc. Historical record of v1 + this v2 re-audit; links to SPEC.
2. Replacement executive summary. Anchored only in canonical (non-archived) docs. Lists every canonical doc with a one-line summary.
3. Replacement checkpoint log. v1 phases preserved as historical record; v2 Phases 0–7 each timestamped.
4. Final CHANGELOG summary section.
5. Run all Verification Commands (including the blacklist grep) and record output in CHANGELOG.
6. `## Status` updated to `current_phase: complete`, `last_completed_phase: 7`.

---

## /skill-creator Follow-On

**Two skills, in this order:**

### Skill 1 — `genome-reader`

Parsing/conversion/lookup substrate. No clinical interpretation. Capabilities: format detection, summary, region extraction across FASTA, FASTQ, VCF, BAM/SAM/CRAM, BED, GFF/GTF, consumer DNA exports. Conversion (consumer DNA → VCF, etc.). rsid lookup. DNA-to-protein translation. HTML FASTQ QC report. Excel variant report. Anti-requirements: no de novo assembly, no read alignment, no variant calling, no network calls except `fetch_assets.py`. **These restrictions are correct for genome-reader and explicitly NOT inherited by genome-decoder.**

### Skill 2 — `genome-decoder`

The interpretation + audit pipeline encoded by this SPEC. Consumes `genome-reader` as a substrate for parsing:
- `genome-reader summarize.py <genome.txt> --json` for source fingerprint (Provenance Block fields).
- `genome-reader lookup.py <genome.txt> --rsids <set> --columns rsid,chrom,pos,genotype` for the base rows of `INDEX_genotype_truth.tsv`. `genome-decoder` adds audit-specific columns (`found`, `source_docs`, `discovered_in_phase`).
- `genome-reader convert.py <genome.txt> --to vcf` (Phase 6) for ClinVar/CPIC coordinate resolution.

Substrate resolution: `$GENOME_READER_PATH`, else the sibling skill `../genome-reader`. A missing or too-old substrate stops the run with a clear message — no silent fallback.

Different rules from `genome-reader`:
- MUST make network calls — WebFetch to CPIC, ClinVar, PharmGKB, PubMed, FDA biomarker table, GWAS Catalog, dbSNP, gnomAD.
- MUST produce health-interpretation claims with the Provenance Block and Non-Negotiable Rules.

**Output format.**
- Working/intermediate: markdown.
- Final user-facing: HTML (self-contained single-file; YAML frontmatter as `<meta>` block; rsid/chr/pos/genotype as `<code>` spans with `data-*` attributes; allow-list citations as `<a href>` with `data-access-date`; semantic `<table>` tags).

Determinism: same inputs + same allow-list snapshot date + same `genome-reader` version produce the same set of provenance blocks and the same delete/rewrite/keep classification.

### Substrate-integration amendment provenance

After the reference implementation's Phase 7 completed and BEFORE `/skill-creator` ran for `genome-decoder`, this SPEC received one targeted amendment: every genome-parsing PowerShell snippet was amended to show the equivalent `genome-reader` invocation as the primary form. SPEC-only change; canonical docs were NOT re-generated. Full amendment scope + per-operation mapping are in `## Phase 7 Amendment — genome-reader Substrate Integration` below.

**Non-genome-parsing operations NOT amended (genome-reader does not cover these):**
- SHA-256 hashing (`Get-FileHash` / `sha256sum`) — for source-genome and INDEX drift detection.
- Filesystem operations (`Get-ChildItem` / `ls`) — for archive-integrity verification.
- Markdown content checks (`Select-String` / `grep`) — for Provenance Summary verification + rsid-pool extraction from archive docs + blacklist enforcement.

These remain PowerShell-or-bash because they are not in genome-reader's domain. The amendment is SURGICAL: only genome-parsing operations (line-count of consumer DNA, assembly detection, rsid genotype lookup, format identification, and VCF conversion for Phase 6 ClinVar/CPIC coordinate resolution) are amended.

---

## Phase 7 Amendment — genome-reader Substrate Integration

**Date applied.** 2026-05-28
**Trigger.** `genome-reader` skill build completed. Per master plan `## /skill-creator Follow-On`, the SPEC receives a targeted amendment BEFORE `/skill-creator` runs for `genome-decoder` so that the genome-decoder build picks up the correct substrate dependency.
**Scope.** SPEC-only. This amendment changes only the SPEC's prescriptions for FUTURE re-audit runs (in particular, the genome-decoder skill build).

### Operation-by-operation mapping

| Phase 0–7 operation | Pre-amendment substrate | Phase 7 amendment substrate | Notes |
|---|---|---|---|
| SHA-256 of source genome (drift detection) | `Get-FileHash -Algorithm SHA256` / `sha256sum` | **UNCHANGED** | Not a genome-reader operation; hash commands stay. |
| File size (byte count) | `Get-Item -Length` / `wc -c` | `genome-reader identify.py <path>` returns `size_bytes` field (parallel) | Either form acceptable. |
| Format identification | (implicit — assumed 23andMe) | `genome-reader identify.py <path>` returns `format` (e.g., `consumer_dna:23andme`) | NEW capability. genome-decoder should call identify.py BEFORE assuming a consumer DNA format. |
| Data-row count | `(Get-Content … \| Measure-Object -Line).Lines` minus header rows | **`genome-reader summarize.py <path> --json` returns `snp_count`** | Primary form post-amendment. |
| Reference assembly (GRCh37 vs GRCh38) | `Get-Content -TotalCount 20 \| Select-String 'build'` | **`genome-reader summarize.py <path> --json` returns `build`** | Primary form post-amendment. Detected from header comments by `detect_consumer_dna_build` in genome-reader's `_common.py`. |
| Per-chromosome SNP distribution | (not previously computed) | `genome-reader summarize.py <path> --json` returns `chromosome_distribution` | NEW capability. Useful for QC + chip-coverage analysis. |
| No-call rate | (not previously computed) | `genome-reader summarize.py <path> --json` returns `no_call_rate` | NEW capability. Useful for QC. |
| Per-rsid genotype lookup + chr:pos extraction (INDEX Phase 0 construction) | PowerShell streaming hashtable | **`genome-reader lookup.py <path> --rsids <pool> --columns rsid,chrom,pos,genotype`** (primary) | Outputs 4-column TSV: `rsid<TAB>chrom<TAB>pos<TAB>genotype`; `not_tested` row for absent rsIDs emits rsid + empty strings. Default invocation without `--columns` still emits `rsid<TAB>genotype` for backward compatibility. |
| Consumer DNA → VCF conversion (Phase 6 ClinVar/CPIC coordinate resolution) | (not previously computed) | `genome-reader convert.py <path> --to vcf` | NEW capability. Requires `fetch_assets.py rsid_grch37` (or `rsid_grch38`) first to populate the rsID map. Unmapped rsIDs skipped + reported. |
| Rsid pool extraction from archive .md docs | `Select-String -Pattern '\brs\d+\b'` / `grep -ohE 'rs[0-9]+'` | **UNCHANGED** | Not a genome-reader operation; markdown grep stays. |
| Archive integrity (file count) | `Get-ChildItem -File \| Measure-Object -Line` / `ls \| wc -l` | **UNCHANGED** | Not a genome-reader operation; filesystem ls stays. |
| Provenance Summary coverage grep | `Select-String -Pattern '^## Provenance Summary'` / `grep '^## Provenance Summary'` | **UNCHANGED** | Not a genome-reader operation. |
| Aspirational blacklist grep | `Select-String -Pattern '<blacklist regex>'` / `grep -nEi '<blacklist regex>'` | **UNCHANGED** | Not a genome-reader operation. Use `grep -i` (case-insensitive). |

### genome-reader invocation reference

Setup (one-time, in the genome-reader repo):

```bash
cd <genome-reader path>
python -m venv .venv
.venv/bin/pip install -r requirements.txt
# Fetch the full dbSNP rsID maps for convert.py — required for the Phase 6 VCF-conversion use case (skip if Phase 6 doesn't need VCF)
.venv/bin/python scripts/fetch_assets.py rsid_grch37  # or rsid_grch38
```

Per-operation invocations (called from `genome-decoder` or directly):

```bash
# Format identification (Phase 0 source-genome registration)
python <genome-reader>/scripts/identify.py <source_genome_path>
# Returns JSON: {"format": "consumer_dna:23andme", "size_bytes": <int>, ...}

# Source-genome summary (Phase 0 source-genome registration)
python <genome-reader>/scripts/summarize.py <source_genome_path> --json
# Returns JSON: {"format": ..., "snp_count": <int>, "build": "GRCh37"|"GRCh38",
#                "chromosome_distribution": {...}, "no_call_rate": <float>}

# Per-rsid genotype lookup with chr:pos projection (Phase 0 INDEX construction)
python <genome-reader>/scripts/lookup.py <source_genome_path> --rsids <pool_file_or_csv> --columns rsid,chrom,pos,genotype
# Returns 4-column TSV: rsid<TAB>chrom<TAB>pos<TAB>genotype; 'not_tested' row for absent
# rsIDs emits the rsID + empty strings in the remaining columns.
# Default without --columns: rsid<TAB>genotype only (backward-compat for callers that
# do not need chr:pos).

# Consumer DNA → VCF conversion (Phase 6 ClinVar/CPIC coordinate resolution)
python <genome-reader>/scripts/convert.py <source_genome_path> --to vcf [--build GRCh37|GRCh38]
# Requires fetch_assets.py rsid_grch37 (or rsid_grch38) first.
# Unmapped rsIDs are skipped with stderr warning.
```

### lookup.py --columns capability

The chr:pos projection gap originally present in genome-reader v1 (`lookup.py`
emitted `rsid<TAB>genotype` only) is closed. `lookup.py` now accepts
`--columns rsid,chrom,pos,genotype` (or any subset / reordering of those 4
columns). Default behavior without `--columns` is unchanged
(`rsid<TAB>genotype` for backward compatibility); explicit `--columns` widens
the projection to the requested fields. `not_tested` rows for absent rsIDs emit
the rsID + empty strings in the remaining columns.

**genome-decoder INDEX construction.** The genome-decoder Phase 0 composes:

```bash
python <genome-reader>/scripts/lookup.py <source_genome_path> --rsids <pool> --columns rsid,chrom,pos,genotype
```

…directly into the INDEX TSV, then adds `found`, `source_docs`, and
`discovered_in_phase` columns post-hoc. The substrate covers the full per-rsid
lookup operation Phase 0 needs.

**Legacy awk bridge (fallback only).** For environments that cannot invoke
genome-reader (a constrained sandbox without Python or without the
genome-reader checkout), the awk fallback is functionally equivalent to
`lookup.py --columns rsid,chrom,pos,genotype` for 23andMe-shape consumer DNA:

```bash
awk -F'\t' 'NR==FNR{a[$0];next} !/^#/ && $1 in a' <pool> <source_genome>
```

New callers should use the substrate; the awk fallback is for environments where
the substrate is unavailable.

### Substrate validation procedure (run per audit)

The substrate is **validated, not assumed**. Before relying on genome-reader,
each audit run confirms it against ITS OWN source genome — there is no recorded
historical PASS baked into this contract, because that would assert a result
that did not run against the live subject's file.

Procedure (Phase 0):

1. Pick a small probe set of rsids already known to be present on the subject's
   chip (for 23andMe v5, any rsid the archive docs cite is a safe probe).
2. Run `summarize.py --json` and record `snp_count`, `build`, `no_call_rate`
   into the plan frontmatter.
3. Run `lookup.py --rsids <probe set> --columns rsid,chrom,pos,genotype`.
4. Confirm the returned rows are internally consistent with the INDEX rows the
   same run produces (same genotype for the same rsid). A mismatch is a STOP
   condition — do not proceed to interpretation on an unvalidated substrate.

| Operation | What to record | Pass condition |
|---|---|---|
| `identify.py` | `format`, `size_bytes` | `format` matches the provider the header declares |
| `summarize.py --json` | `snp_count`, `build`, `no_call_rate` | `build` matches the header's assembly declaration; counts are stable across re-runs |
| `lookup.py --columns …` | genotype per probe rsid | every probe rsid resolves to a genotype consistent with the INDEX |

All values recorded are the LIVE subject's — they live only in the private
output directory and plan frontmatter, never in this bundled contract.

### Substrate enhancement candidates (non-blocking)

Two enhancement candidates surfaced during substrate integration, filed against
the substrate's issue tracker for future genome-reader work. Neither blocks the
`genome-decoder` build:

- **`extract.py`: consumer DNA support for `--region chr:start-end`.** Extends
  `extract.py` to cover consumer DNA files (currently FASTA / VCF / BAM / GFF /
  GTF / BED only). Enables `genome-decoder`'s Phase 6 ACMG SF v3 gene-coordinate-range
  scan against consumer DNA without an awk bridge.
- **Public API for `iter_consumer_dna`.** Re-exports `iter_consumer_dna` +
  `detect_consumer_dna_build` from a public module so `genome-decoder` can
  consume the substrate as a Python library rather than only via CLI invocations.

### Out-of-scope for this amendment

- The reference implementation is NOT regenerated. Per Non-Negotiable Rule 9 (archive immutability) + Phase 7 atomicity, the reference implementation's canonical docs stay as-produced.
- The `## Verification Commands` block below retains its current PowerShell-primary form because the verification commands cover non-genome-parsing operations (filesystem `ls`, markdown grep, hash) where the amendment does not apply.
- The Aspirational Phrase Blacklist enforcement procedure (Appendix below) is NOT amended — it's a grep-against-markdown operation, not a genome-parsing operation.

---

## Verification Commands

Run after Phase 7. All output captured in CHANGELOG.

```powershell
# 1. Archive integrity
(Get-ChildItem '<archive_dir>' -File).Count
# Expected: matches Phase 0 archive manifest

# 2. Source genome SHA-256 matches plan frontmatter
Get-FileHash '<source_genome_path>' -Algorithm SHA256
# Expected: matches plan frontmatter

# 3. Provenance block coverage
Get-ChildItem '<output_dir>\*.md' -Exclude 'CHANGELOG.md','SPEC_*.md','INDEX_*.md','REPORT_*.md' |
  ForEach-Object { if (-not (Select-String -Path $_ -Pattern '^## Provenance Summary' -Quiet)) { $_.Name } }
# Expected: empty
```

```text
# 4. Aspirational-language audit (narrow check)
Grep pattern: "(may benefit|might consider|could be helpful|future possibility|patients with this variant often)"
glob: "<output_dir>\*.md"
Expected: zero canonical files

# 4b. Aspirational Phrase Blacklist (full token sweep) — across canonical docs, prompts, plan, SPEC
Grep pattern: "\\b(e\\.g\\.|etc\\.|others|including but not limited to|may|might|could|should consider|likely|roughly|approximately|best|recommended|prefer|optional|if applicable|where supported|as needed)\\b"
glob: "<output_dir>\*.md" then "<prompts_dir>\*.md" then plan + SPEC
Expected: every hit justified (verbatim quote with archive attribution OR in Glossary/Appendix/Stable-Terminology exempted contexts) OR fixed.

# 5. Rsid traceability — every rsid in canonical docs is in INDEX with `found = y`
# 6. Cross-doc genotype consistency — sample 10 rsids referenced in ≥2 canonical docs; reported genotypes match
# 7. Continuation prompts present — phase0 through phase7 exist
```

---

## Glossary

- **rsid (rs number).** Reference SNP identifier from dbSNP.
- **SNP.** Single Nucleotide Polymorphism.
- **Genotype.** Pair of alleles at a position.
- **GRCh37 / hg19.** Reference human genome assembly used by 23andMe exports from 2024.
- **Provenance Block.** Mandatory YAML+markdown header on every replacement doc.
- **CPIC.** Clinical Pharmacogenetics Implementation Consortium.
- **PharmGKB.** Pharmacogenomics Knowledge Base.
- **ClinVar.** NCBI's database of variant-disease relationships.
- **GWAS Catalog.** EBI's catalog of published genome-wide association studies.
- **PMID.** PubMed identifier.
- **VCV.** ClinVar Variant accession.
- **ACMG SF v3.** American College of Medical Genetics Secondary Findings list, version 3.
- **Archive-and-replace.** This SPEC's edit strategy.
- **Aspirational claim.** See Non-Negotiable Rules, rule 1, and the Blacklist appendix.
- **Allow-list citation.** Citation resolving to one of the sources in Evidence Sources.

---

## Appendix: Aspirational Phrase Blacklist

Enforceable encoding of Non-Negotiable Rule 1(c).

### Token list

| Token | Reason |
|---|---|
| `e.g.` | Introduces optional examples where an enumerable list is required. |
| `etc.` | Implies open-ended set; use explicit enumeration or deterministic selection rule. |
| `others` | Same as `etc.`. |
| `including but not limited to` | Same as `etc.`. |
| `may` | Hedges current state; use the observed fact or remove the sentence. |
| `might` | Same. |
| `could` | Same. |
| `should consider` | Soft directive; use a specific action grounded in CPIC/FDA/ClinVar. |
| `likely` | Speculation about magnitude; use a quantified value or remove. |
| `roughly` | Same. |
| `approximately` | Same, when used about a recommendation. Permitted when describing chip-coverage percentages backed by a numeric calculation. |
| `best` | Implies preference without evidence; use a specific action. |
| `recommended` | Permitted only when paraphrasing an allow-list source with citation immediately following. |
| `prefer` | Same as `recommended`. |
| `optional` | Implies a decision left to the executor; use strict yes/no with a condition. |
| `if applicable` | Same as `optional`. |
| `where supported` | Same as `optional`. |
| `as needed` | Same as `optional`. |

### Scope of enforcement

- **In scope.** Every operational instruction and every clinical/health/dietary claim in: canonical docs, continuation prompts, master plan, this SPEC.
- **Out of scope.**
  - Glossary sections (illustrative definitions).
  - Verbatim quotes from archive docs inside markdown blockquotes with explicit `[verbatim from archive\<dir>\<filename>]` attribution.
  - This Appendix itself.
  - Tokens appearing inside inline-code spans (`` ` ``-delimited) or fenced code blocks when they are part of a regex/grep pattern definition, a documented identifier citation, or example syntax. The token is being CITED as a search target or as data, not USED as natural-language hedging.

### Stable-terminology exemption

These terms from allow-list sources are permitted as verbatim identifiers:
- ClinVar pathogenicity classes: `pathogenic`, `likely-pathogenic`, `benign`, `likely-benign`, `uncertain-significance`. The word `likely` is permitted only as part of these hyphenated ClinVar classes.
- CPIC evidence levels: `Level A`, `Level B`, `Level C`, `Level D`.
- ACMG recommendation tiers when quoted verbatim with their source citation.

A token from the blacklist used as part of these stable terms requires a citation to the source on the same line.

### Enforcement procedure

```
Grep pattern: "\\b(e\\.g\\.|etc\\.|others|including but not limited to|may|might|could|should consider|likely|roughly|approximately|best|recommended|prefer|optional|if applicable|where supported|as needed)\\b"
glob: <file under audit>
output_mode: content
-n: true
```

For each hit: (i) inside an archive-attributed blockquote → permitted; (ii) inside Glossary/Appendix or under the stable-terminology exemption → permitted; (iii) otherwise → rewrite or remove. Re-run grep until zero non-permitted hits remain.

---

## Appendix: 23andMe Raw Genome File Structure

```
Format:       Tab-separated values
Encoding:     ASCII
Line endings: Unix (LF) typically; verify in Phase 0

Lines 1-N:    Header comments (each prefixed with '#')
              Includes provider disclaimer, file-generation timestamp,
              and reference-assembly declaration (e.g., "build 37").

Line N+1:     Column header
              # rsid	chromosome	position	genotype

Lines N+2..end:  SNP data rows
              Columns:
                1. rsid          — illustrative value: rs4477212
                2. chromosome    — 1-22, X, Y, MT
                3. position      — base-pair position on the declared assembly
                4. genotype      — two-letter call or '--' for no-call

Typical line count: 600k-700k rows for 23andMe v5 chips.
```

To verify line count and assembly cold (Phase 7 amendment: use `genome-reader summarize.py` as the primary form; PowerShell forms retained as fallback when genome-reader is unavailable):

```bash
# Primary form — via genome-reader (Phase 7 amendment)
python /path/to/genome-reader/scripts/summarize.py '<source_genome_path>' --json
# JSON output includes:
#   - snp_count        — number of SNP data rows (excludes header comments)
#   - build            — "GRCh37" or "GRCh38" detected from header comments
#   - chromosome_distribution — per-chromosome row count
#   - no_call_rate     — fraction of '--' genotype calls
```

```powershell
# Fallback form — pure PowerShell (no genome-reader dependency)
(Get-Content '<source_genome_path>' | Measure-Object -Line).Lines
Get-Content '<source_genome_path>' -TotalCount 20 | Select-String 'build'
```

The total file line count (header comments + data rows) is `snp_count` (from genome-reader) plus the count of `#`-prefixed header lines plus 1 (column header). For 23andMe v5 chip exports the header is typically 20 lines (19 `#` comments + 1 column header); for AncestryDNA / MyHeritage the header structure differs and the genome-reader-substrate handles per-provider parsing.

---

## Reference Implementation Pointer

The reference implementation that proves this workflow is a **synthetic
reference fixture**. Real per-run output is written to the private (gitignored)
output directory and is never committed.

- Subject: `<subject label>` (synthetic in any repository artifact)
- Source: `<source_genome_path>` (SHA-256 recorded in plan frontmatter at Phase 0)
- Output: `<output_dir>`
- Plan: `<master plan path>`
- Phase 0 completed: `<YYYY-MM-DD>`

If any phase deliverable is ambiguous in this SPEC, consult the skill's
synthetic test fixtures (`tests/`) and the bundled assets
(`assets/allowlist_sources.json`, `assets/blacklist_phrases.txt`,
`assets/templates/`) for the canonical encoding. The skill is self-contained:
no private subject archive is required to interpret this contract.
