---
name: genome-reader
description: Parses, summarizes, queries, and converts DNA and genome data files locally. Use whenever the user shares a FASTA, FASTQ, VCF, BAM/SAM/CRAM, BED, GFF/GTF, or a 23andMe / AncestryDNA / MyHeritage raw export — even if they don't name the format. Use for sequence inspection, variant counts, genotype lookups by rsID, region extraction, FASTQ QC, VCF Excel reports, format conversion, and DNA→protein translation. Do not use for de novo assembly, read alignment, variant calling, phylogenetic trees, or anything requiring an external paid API or uploading user data.
---

# genome-reader

A local, offline-first toolkit for inspecting and converting common DNA and
genome data files. Every capability is a single-purpose Python script under
`scripts/`. Each one writes results to stdout (or a named output file in the
case of reports). Warnings go to stderr.

## When to use

Use this skill whenever the user references a genomics file — explicit
formats (FASTA, FASTQ, VCF, BAM, BED, GFF, GTF, CRAM, SAM) or consumer
exports (23andMe `.txt`, AncestryDNA `.txt`, MyHeritage `.csv`) — and wants
to:

- ask what a file is or how many records it contains
- get a numeric summary (read counts, variant breakdown, coverage proxy, GC%)
- pull a region from a FASTA/VCF/BAM/GFF
- look up genotypes for specific rsIDs in a consumer DNA file
- convert between supported format pairs
- translate DNA to protein in any reading frame
- produce a FASTQ QC HTML report or a VCF Excel report

Trigger even if the user says "my genome", "my DNA file", "the sequencing
output" — sniff the file with `identify.py` first.

## When not to use

This skill refuses, by design, to attempt:

- de novo assembly
- read alignment or variant calling (only reading already-aligned/called data)
- phylogenetic tree construction
- any operation that requires uploading user data to a third party
- any operation that requires a paid API key

If the user asks for one of those, say so plainly and stop.

## Setup

The skill bundles `requirements.txt` with pinned versions of `biopython`,
`pysam`, `pyfaidx`, `cyvcf2`, `pandas`, `matplotlib`, `openpyxl`.

Container / sandboxed environment:

    pip install --break-system-packages -r requirements.txt

Normal environment:

    pip install -r requirements.txt

`pysam` and `cyvcf2` ship binary wheels for Linux and macOS that bundle
htslib; no system packages are required for those platforms.

## Capabilities

### identify.py — what is this file?

    python scripts/identify.py <path>

Reads only enough bytes to classify the file. Prints JSON:

    {
      "format": "vcf" | "fasta" | "fastq" | "bam" | "sam" | "cram"
              | "bed" | "gff" | "gtf"
              | "consumer_dna:23andme" | "consumer_dna:ancestrydna"
              | "consumer_dna:myheritage"
              | "unknown",
      "compressed": true | false,
      "record_count_estimate": <int|null>,
      "size_bytes": <int>,
      "index_present": true | false
    }

`record_count_estimate` is a quick projection from a 64 KB sample; it is
`null` for BAM/CRAM where the cheap path requires an index.

### summarize.py — numeric summary

    python scripts/summarize.py <path> [--json]

Output depends on the detected format:

| format          | reported                                                                                          |
|-----------------|---------------------------------------------------------------------------------------------------|
| FASTA           | sequence count, total length, min/median/mean/max length, N50, GC%, ambiguous base count          |
| FASTQ           | read count, length distribution, mean per-base quality, Phred encoding (33/64), adapter hit count |
| VCF             | variant count, SNV/indel/MNP/SV split, Ts/Tv, per-chrom counts, PASS vs filtered, sample list     |
| BAM/SAM/CRAM    | read count, mapped vs unmapped, duplication rate, contig list, coverage proxy if index present    |
| BED/GFF/GTF     | feature count, feature types, span per chromosome, sources                                        |
| Consumer DNA    | SNP count, chromosome distribution, build (GRCh37/38), no-call rate                               |

Pass `--json` for machine-readable output.

### extract.py — pull a region

    python scripts/extract.py <path> --region chr:start-end

Region uses 1-based, inclusive coordinates. Works on FASTA (sequence), VCF
(variants in window), BAM (reads in window), GFF/GTF/BED (features
overlapping the window). Builds the `.fai` / `.tbi` / `.bai` index if
missing and the directory is writable; otherwise reports the missing
index and exits.

### convert.py — format conversion

    python scripts/convert.py <input> --to <target> [--build GRCh37|GRCh38]

Only these conversions are allowed; everything else is refused with a
clear error:

| from           | to        | notes                                                                |
|----------------|-----------|----------------------------------------------------------------------|
| FASTA          | tsv       | columns: id, length, gc, sequence                                    |
| FASTQ          | fasta     | qualities dropped                                                    |
| VCF            | tsv / csv | one row per variant; every INFO key gets a column                    |
| BED            | gff       | feature type set to `region`; block fields dropped (warns)           |
| GFF / GTF      | bed       | source and feature type dropped (warns)                              |
| consumer DNA   | vcf       | needs rsID map — run `fetch_assets.py` first; unmapped rsIDs skipped |

### lookup.py — genotypes for specific rsIDs

    python scripts/lookup.py <consumer_dna_file> --rsids <file_or_csv>

`--rsids` can be a path (one rsID per line, `#` comments allowed) or a
comma-separated list. Output is a two-column TSV (`rsid<TAB>genotype`);
rsIDs not present in the input are reported as `not_tested`.

### translate.py — DNA → protein

    python scripts/translate.py <fasta> --frame <1|2|3|-1|-2|-3|all> [--table 1]

Uses the NCBI standard code (table 1) by default. Tables 1, 2, 4, 5, 11
are bundled (see `assets/genetic_codes.json`). Stop codons render as `*`.

### qc_report.py — FASTQ QC report

    python scripts/qc_report.py <fastq>

Writes `<input>.qc.html` next to the input. Self-contained file:
per-base quality boxplot, per-read mean quality histogram, length
distribution, GC% distribution, per-position N content, top 20
overrepresented sequences. Uses matplotlib only — no network calls.

### variants_report.py — VCF Excel workbook

    python scripts/variants_report.py <vcf>

Writes `<input>.variants.xlsx` next to the input. Sheets: `summary`,
`by_chromosome`, `top_quality` (top 100 by QUAL), `frameshift_candidates`
(indel length not divisible by 3), `filtered_out`.

## Reference data

Bundled under `assets/`:

- `genetic_codes.json` — NCBI translation tables 1, 2, 4, 5, 11
- `rsid_grch37.tsv.gz`, `rsid_grch38.tsv.gz` — minimal stubs covering a
  handful of well-known consumer-chip SNPs (ApoE, MTHFR, Factor V Leiden,
  Factor II). Enough for the test suite and small smoke checks.
- `README.md` — provenance for every asset

The full ~38M-row dbSNP common-variants maps exceed the 25 MB bundle
budget, so they are fetched on demand by `scripts/fetch_assets.py`:

    python scripts/fetch_assets.py rsid_grch37
    python scripts/fetch_assets.py rsid_grch38

The fetcher writes `assets/rsid_grch{37,38}.full.tsv.gz` next to the
bundled stub — it does not overwrite the stub. `convert.py` prefers the
`.full.tsv.gz` map when present and falls back to the stub otherwise.
The `.full.tsv.gz` files are gitignored.

`fetch_assets.py` prints what it will download and asks for confirmation
before any network call. Pass `--yes` to skip the prompt. Pass
`--rsid-map <path>` to `convert.py` to use a custom map outside `assets/`.

## Privacy

Consumer DNA files contain identifying genetic information. The skill
processes them locally; nothing is transmitted unless the user
explicitly opts into an online annotation step.

This version of the skill ships no online annotation step. The only
network access in the codebase is `scripts/fetch_assets.py`, which
downloads reference data from NCBI and never reads or sends user input.

## Limits

- BAM/CRAM record counts are reported as `null` by `identify.py`; use
  `summarize.py` for exact counts (it reads the whole file or the index).
- `extract.py` requires the appropriate index. If the index is missing and
  the file lives in a read-only directory, extraction fails — copy the file
  somewhere writable.
- Consumer DNA → VCF skips rsIDs not present in the bundled or fetched
  map and reports the skip count.
- `qc_report.py` and `variants_report.py` hold the full file in working
  memory for charting/aggregation. For files larger than your RAM, split
  upstream.
- Conversions outside the supported list are refused. There is no silent
  approximation — the script exits non-zero.
