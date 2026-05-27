# Bundled assets

## genetic_codes.json
NCBI genetic-code translation tables 1, 2, 4, 5, 11. Table 1 stores the full
codon→aa map; others store only the differences from table 1 (under
`overrides`). Sourced from the NCBI Taxonomy genetic-code definitions
(https://www.ncbi.nlm.nih.gov/Taxonomy/Utils/wprintgc.cgi).

## rsid_grch37.tsv.gz, rsid_grch38.tsv.gz
**Bundled minimal stubs** covering the test-suite rsIDs plus a few
well-known consumer-chip variants (ApoE rs429358/rs7412, MTHFR rs1801133,
Factor II rs1799963, Factor V Leiden rs6025, HLA tag rs4324498).

These stubs let `convert.py <consumer_dna> --to vcf` succeed out of the
box on a tiny set of rsIDs. For real consumer-DNA conversions, fetch the
chip-union map below.

## rsid_grch37.full.tsv.gz, rsid_grch38.full.tsv.gz (not bundled)
The chip-union rsID→(chrom, pos, ref, alt) map covering the SNPs on
23andMe V5 and AncestryDNA v2. Build it locally with:

    python scripts/fetch_assets.py rsid_grch37
    python scripts/fetch_assets.py rsid_grch38

The output `.full.tsv.gz` files are gitignored. `convert.py` prefers them
over the bundled stub when present.

### Sources used by `fetch_assets.py`

The fetcher downloads the following on first use, on your machine, from
each publisher directly:

| Source | URL | Last verified | Purpose |
|---|---|---|---|
| Illumina Infinium Global Screening Array v1.0 manifest (zip → CSV) | https://webdata.illumina.com/downloads/productfiles/global-screening-array/v1-0/infinium-global-screening-array-v1-0-c1-manifest-file-csv-build37.zip | 2026-05-27 (server last-modified 2018-06-01) | rsID set covering the 23andMe V5 base chip |
| Illumina HumanOmniExpress-12 v1.1 manifest (CSV) | https://webdata.illumina.com/downloads/ProductFiles/HumanOmniExpress/v1-1/HumanOmniExpress-12-v1-1-C.csv | 2026-05-27 (server last-modified 2018-04-23) | rsID set covering the AncestryDNA v2 base chip (proxy — see deviation below) |
| dbSNP common-variants VCF build 151, GRCh37 | https://ftp.ncbi.nih.gov/snp/organisms/human_9606_b151_GRCh37p13/VCF/common_all_20180423.vcf.gz | 2018-04-23 | `(chrom, pos, ref, alt)` lookup for the chip-union rsIDs at GRCh37 |
| dbSNP common-variants VCF build 151, GRCh38 | https://ftp.ncbi.nih.gov/snp/organisms/human_9606_b151_GRCh38p7/VCF/common_all_20180418.vcf.gz | 2018-04-18 | same, at GRCh38 |

### Spec deviation — AncestryDNA v2 via OmniExpress proxy

Issue #6 references "the 23andMe v5 and AncestryDNA v2 chip manifests."
Neither 23andMe nor AncestryDNA publishes its actual chip manifest;
both chips are private customizations of Illumina base arrays:

- **23andMe V5** is built on **Illumina GSA v1**.
- **AncestryDNA v2** is built on **Illumina HumanOmniExpress-12 v1.1**
  (no public AncestryDNA-specific manifest exists).

The fetcher uses both Illumina base manifests as the closest publicly
available approximation. The genomics community
([albertodesouza/genomics](https://github.com/albertodesouza/genomics/blob/989545e4065d0d6602145e5153cb792ee6bff1eb/vcf_to_23andme/README.md))
treats these manifests as ~99% accurate vs the actual deployed chip,
because the consumer companies add and drop ~1% of probes during chip
customization. Output should therefore not be treated as the literal
chip rsID set — it is the closest defensible public proxy.

### Illumina manifest license

Illumina manifest files are proprietary to Illumina, Inc. The Illumina
Array Downloads page
(https://support.illumina.com/array/downloads.html) states that the
downloadable materials "are proprietary to Illumina, Inc., and are
intended solely for the use of its customers and for no other purpose
than use with Illumina's products or services."

This repository does NOT ship any Illumina-derived data. `fetch_assets.py`
arranges for each user to download the manifests directly from Illumina's
servers on their own machine, in their role as Illumina's customer. The
extracted rsID list and the dbSNP-joined output stay local to that user's
checkout and are gitignored.
