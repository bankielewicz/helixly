<!--
  +-------------------------------------------------+
  |   H E L I X Y A I  -  your genome, made legible |
  +-------------------------------------------------+
-->

# HelixyAI

> Re-audit a consumer DNA export and your prior AI genome documents into a **deterministic, evidence-cited, self-contained HTML report** — every claim traced to your own genotype and an authoritative source.

[![status](https://img.shields.io/badge/status-alpha-2f7d6b)](#)
[![skills](https://img.shields.io/badge/Claude_Code-2_skills-235e51)](#usage)
[![evidence](https://img.shields.io/badge/citations-allow--list_only-3a6491)](#evidence--provenance-discipline)
[![privacy](https://img.shields.io/badge/runs-100%25_local-a9572a)](#privacy)
[![reproducible](https://img.shields.io/badge/output-byte--deterministic-2f7d6b)](#)
[![license](https://img.shields.io/badge/license-TBD-8b97a1)](#license)

**🌐 [helixyai.com](https://helixyai.com)** &nbsp;·&nbsp; **[▶ View a live sample report](https://helixyai.com/sample-report.html)**

```
  consumer DNA export
  (23andMe / Ancestry /     +-------------------+        +-------------------------------+
   MyHeritage)        --->  |   genome-reader   |  --->  |        genome-decoder         |  --->  self-contained
  + prior AI docs           |    (substrate)    |  parse |   (8-phase audit + rebuild)   |        HelixyAI report
                            +-------------------+        +-------------------------------+        (1 index +
                             detect / lookup              INDEX / audit / rebuild / verify        per-doc pages)
                             convert / translate          gated agent interpretation
```

HelixyAI is two Claude Code **skills**. `genome-reader` is the parsing substrate; `genome-decoder` is the
interpretation-and-audit pipeline built on top of it. Deterministic Python tools do the mechanical, reproducible work;
the agent does interpretation, always written through a gated path.

---

## What it does

You hand HelixyAI two things:

1. a **consumer DNA export** (23andMe / AncestryDNA / MyHeritage), and
2. a folder of **prior AI-generated genome-analysis documents**.

It re-audits both and rebuilds them into a single, navigable HelixyAI report in which **every clinical claim is cited to
an rsID present in your data and to an authoritative source** — and every unsupported or aspirational claim from the
prior documents has been removed. The report is self-contained HTML that runs anywhere, offline, with no external
dependencies.

---

## How it works

Two tracks, working together:

- **Deterministic Python tools** produce the mechanical, reproducible artifacts. The genotype-truth **INDEX**, the audit
  findings, the Phase-6 candidate set, and the final rendered HTML are **byte-deterministic for the same inputs**.
- **The agent** does interpretation — reading the tools' output and writing plain-English meaning — but only through a
  **gated path** that enforces the evidence rules below at write time.

### The 8-phase workflow

| Phase | Stage | Track | What happens |
|:-----:|-------|:-----:|--------------|
| **0** | Genotype-truth INDEX | tool | Build the source-of-truth index of observed genotypes directly from the raw chip. |
| **1** | Provenance / aspirational-claim audit | tool | Scan prior documents for unsupported and aspirational claims against the INDEX. |
| **2** | Cross-document corrections | agent · gated | Reconcile contradictions across prior docs; rewrite to the genotype truth. |
| **3** | Pharmacogenomics | agent · gated | Genotype-guided drug response, restated from CPIC / FDA PGx guidance. |
| **4** | MTHFR / methylation | agent · gated | Methylation-cycle variants and downstream folate processing in context. |
| **5** | Project-specific context | agent · gated | Apply the questions and focus areas particular to this subject's project. |
| **6** | Net-new findings scan | tool | Deterministic candidate set across ClinVar, ACMG SF, and CPIC for review. |
| **7** | Executive summary + final verification | agent + verify | Write the summary, then run a final verification pass before the report is sealed. |

---

## Evidence & provenance discipline

This is the core of HelixyAI. **No clinical claim reaches the page** unless it satisfies all three rules:

1. **(a) Cite an rsID present in the INDEX**, with the subject's *observed* genotype.
2. **(b) Cite an allow-list source.**
3. **(c) Be a current observation** — present tense, about what *is*. Never a hedge, never an aspiration.

Aspirational and hedge phrasing is **deleted, not softened** — enforced by an automated blacklist gate at write time.

**Allow-list sources:** PubMed · ClinVar · CPIC · PharmGKB · FDA PGx table · GWAS Catalog · dbSNP · gnomAD

Each rebuilt document carries a **provenance block** recording the source assembly, the source file SHA-256, the
allow-list snapshot date, the genome-reader version, and what it supersedes.

```text
✗ deleted:  "This variant may suggest you could be predisposed to optimizing your metabolic potential."
✓ written:  "rs4244285 is observed as G/A — intermediate CYP2C19 activity (CPIC Level A)."
```

---

## Install & setup

> This was previously undocumented. The steps below are required and **order matters** — `genome-decoder` delegates all
> parsing to the `genome-reader` substrate, so the reader's virtualenv must exist first.

```bash
# 1. Place both skills as siblings (Claude Code project- or user-level skills dir)
#    e.g. .claude/skills/genome-reader  and  .claude/skills/genome-decoder

# 2. Build the genome-reader substrate's virtualenv (REQUIRED — genome-decoder delegates all parsing to it)
cd <skills>/genome-reader
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# optional, only for the Phase-6 VCF coordinate path:
#   .venv/bin/python scripts/fetch_assets.py rsid_grch37   # or rsid_grch38

# 3. Install genome-decoder's own deps (network/parse paths)
pip install -r <skills>/genome-decoder/requirements.txt

# 4. Substrate resolution: genome-decoder finds genome-reader via $GENOME_READER_PATH,
#    else the sibling ../genome-reader. Set GENOME_READER_PATH to override.
```

**Substrate resolution.** `genome-decoder` locates the reader in this order:

1. the `$GENOME_READER_PATH` environment variable, if set;
2. otherwise the sibling directory `../genome-reader`.

Set `GENOME_READER_PATH` to override the default.

---

## Usage

### Invoke through Claude Code

Place both skills in your skills directory, then simply ask Claude Code to:

> **“re-audit / rebuild / verify my genome analysis.”**

Point it at your DNA export and the folder of prior documents, and the 8-phase workflow runs end to end.

### Deterministic CLIs

Each phase is also a standalone, deterministic CLI you can run directly:

| CLI | Description |
|-----|-------------|
| `index_build.py` | Build the genotype-truth INDEX from the raw chip (Phase 0). |
| `audit.py` | Audit prior documents for unsupported / aspirational claims against the INDEX (Phase 1). |
| `discover.py` | Generate the deterministic net-new findings candidate set — ClinVar / ACMG SF / CPIC (Phase 6). |
| `rebuild.py` | Rebuild documents with rsID + allow-list citations and a provenance block, then render the HTML. |
| `verify.py` | Run the final verification pass over the rebuilt report (Phase 7 gate). |

### Tests

```bash
python -m pytest skills/genome-decoder/tests/ -q
```

---

## Output

A **self-contained HelixyAI HTML report** — inline CSS/SVG, no external CDN/script/font loads, viewable offline:

- **one index page** — provenance overview, at-a-glance highlights, and a searchable/filterable contents grid;
- **per-document pages** — one for each rebuilt analysis, interlinked and cross-referenced.

rsIDs, chromosome positions, and genotypes are rendered as monospace `<code>` chips so the evidence chain is legible at
a glance. The same inputs always produce the same report.

> **See it for yourself:** [helixyai.com/sample-report.html](https://helixyai.com/sample-report.html) renders a complete
> (synthetic) HelixyAI report — index, per-document pages, provenance blocks, and citation chips.

---

## Privacy

- **Local-first.** All parsing and rendering run **on your machine**. There is no HelixyAI server in the loop.
- **Never uploaded.** Your DNA export and the generated outputs are never sent off-device.
- **Never committed.** Outputs and source data are never written to version control.

---

## Reproducible

> **Same inputs + same allow-list snapshot date + same genome-reader version → the same report.**

The INDEX, audit findings, Phase-6 candidate set, and rendered HTML are byte-deterministic, so a report can be rebuilt
and independently re-verified.

---

## Medical disclaimer

**HelixyAI is not a diagnostic tool.** It restates guidance from authoritative sources (CPIC / FDA / peer-reviewed
literature) only. It does not diagnose. **Every clinical recommendation ends with “consult your prescribing
clinician.”** Do not start, stop, or change any medication or treatment based on a HelixyAI report.

---

## Not for

HelixyAI does **not** perform, and is **not** intended for:

- ❌ **Diagnosis** of any condition.
- ❌ **De-novo assembly.**
- ❌ **Alignment.**
- ❌ **Variant calling.**

It re-audits and rebuilds *existing* analysis from a consumer genotype export — it does not process raw sequencing
reads.

---

## License

_TBD — license placeholder._

---

<sub>HelixyAI · [helixyai.com](https://helixyai.com) · Your genome, made legible. Reports are informational and, in demonstrations, entirely
synthetic — all identifiers, rsIDs, genotypes, and citations are fictional.</sub>
