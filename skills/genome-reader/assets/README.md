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
box on a tiny set of rsIDs.

## rsid_grch37.full.tsv.gz, rsid_grch38.full.tsv.gz (not bundled)
For real conversions you need the full dbSNP common-variants map. Get it
with

    python scripts/fetch_assets.py rsid_grch37
    python scripts/fetch_assets.py rsid_grch38

The fetcher streams dbSNP build 151 common-variants VCFs from NCBI
(https://ftp.ncbi.nih.gov/snp/organisms/) and writes a separate
`.full.tsv.gz` file next to the stub. The bundled stub is **not**
overwritten. `convert.py` prefers the `.full.tsv.gz` map when present
and falls back to the stub otherwise.

The `.full.tsv.gz` files are gitignored (~1.5 GB raw download). Source
dates: dbSNP b151, 2018-04-23 for GRCh37, 2018-04-18 for GRCh38.
Coverage of the full maps: ~38M common SNPs — superset of every SNP on
23andMe v5 and AncestryDNA v2 chips. The fetcher confirms before any
network call.
