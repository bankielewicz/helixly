#!/usr/bin/env python3
"""Fetch optional reference assets that are too large to bundle in the skill.

Currently supported:
  rsid_grch37   — rsID → (chrom, pos, ref, alt) map at GRCh37 coords
  rsid_grch38   — same at GRCh38 coords

The map is the union of rsIDs on the Illumina chips that underlie 23andMe V5
and AncestryDNA v2, joined against dbSNP common-variants for coordinates.
Sources downloaded by this script (each user downloads directly from the
publisher, so each user is the publisher's customer for the file):

  Illumina GSA v1 manifest (23andMe V5 base chip)
  Illumina HumanOmniExpress-12 v1.1 manifest (AncestryDNA v2 proxy + 23andMe V3 base)
  dbSNP common-variants VCF (build 151) for the requested coordinate system

Note: 23andMe and AncestryDNA customize their chips, adding/removing ~1% of
probes vs the Illumina base manifest. The genomics community treats the base
manifests as ~99%-accurate proxies. AncestryDNA v2 specifically does not ship
a public manifest; HumanOmniExpress-12 v1.1 is the most defensible public
proxy. See assets/README.md for the deviation disclosure.

Illumina materials are proprietary to Illumina, Inc.; downloading via this
script puts you in the role of Illumina's customer per their downloads-page
terms. The extracted rsID list and the rsID→(chrom,pos,ref,alt) join output
live in your local assets/ directory and are gitignored.

Network timeout: connect + per-chunk read default is 30 seconds. Override by
setting the HELIXLY_FETCH_TIMEOUT environment variable (seconds, float ok).

Usage:
  python scripts/fetch_assets.py <name> [<name> ...]
  python scripts/fetch_assets.py --yes <name>           # skip confirmation
"""

from __future__ import annotations

import gzip
import io
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 30


def _timeout_seconds() -> float:
    raw = os.environ.get("HELIXLY_FETCH_TIMEOUT")
    if raw:
        try:
            return float(raw)
        except ValueError:
            print(
                f"warning: ignoring invalid HELIXLY_FETCH_TIMEOUT={raw!r}, "
                f"using default {DEFAULT_TIMEOUT_SECONDS}s",
                file=sys.stderr,
            )
    return DEFAULT_TIMEOUT_SECONDS


ASSETS = Path(__file__).resolve().parent.parent / "assets"

ILLUMINA_MANIFEST_URLS = {
    "gsa_v1": {
        "url": "https://webdata.illumina.com/downloads/productfiles/global-screening-array/v1-0/infinium-global-screening-array-v1-0-c1-manifest-file-csv-build37.zip",
        "kind": "zip",
        "chip_name": "Illumina Infinium Global Screening Array v1.0",
        "covers": "23andMe V5",
    },
    "omniexpress_v1_1": {
        "url": "https://webdata.illumina.com/downloads/ProductFiles/HumanOmniExpress/v1-1/HumanOmniExpress-12-v1-1-C.csv",
        "kind": "csv",
        "chip_name": "Illumina HumanOmniExpress-12 v1.1",
        "covers": "AncestryDNA v2 (proxy) + 23andMe V3",
    },
}

DBSNP_URLS = {
    "GRCh37": "https://ftp.ncbi.nih.gov/snp/organisms/human_9606_b151_GRCh37p13/VCF/common_all_20180423.vcf.gz",
    "GRCh38": "https://ftp.ncbi.nih.gov/snp/organisms/human_9606_b151_GRCh38p7/VCF/common_all_20180418.vcf.gz",
}

SOURCES = {
    "rsid_grch37": {
        "build": "GRCh37",
        "out": "rsid_grch37.full.tsv.gz",
        "approx_mb": 1900,
    },
    "rsid_grch38": {
        "build": "GRCh38",
        "out": "rsid_grch38.full.tsv.gz",
        "approx_mb": 1900,
    },
}


def _confirm(name: str, info: dict) -> bool:
    print(f"\nasset:  {name}")
    print(f"build:  {info['build']}")
    print(f"target: {ASSETS / info['out']}")
    print(f"this will download:")
    for key, mi in ILLUMINA_MANIFEST_URLS.items():
        print(f"  - {mi['chip_name']} manifest ({mi['covers']}): {mi['url']}")
    print(f"  - dbSNP common variants build 151 for {info['build']}: {DBSNP_URLS[info['build']]}")
    print(f"approx: ~{info['approx_mb']} MB total")
    print(
        "Illumina manifest files are proprietary to Illumina, Inc.; by "
        "downloading you accept Illumina's terms (their downloads page "
        "restricts use to Illumina customers and uses tied to Illumina "
        "products or services)."
    )
    ans = input("proceed? [y/N] ").strip().lower()
    return ans == "y"


def _extract_rsids_from_manifest_csv(text: str) -> set[str]:
    """Parse an Illumina manifest CSV and return the set of rsIDs from [Assay].

    Illumina manifests are sectioned: [Header], [Assay], [Controls]. Probe data
    lives in [Assay]; the first row after the section header is a column header
    (typically including 'Name') and subsequent rows are probes. The 'Name'
    column contains the rsID for SNP probes (and Illumina-internal IDs for the
    rest, which we drop).
    """
    rsids: set[str] = set()
    in_assay = False
    name_idx: int | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "[Assay]":
            in_assay = True
            continue
        if in_assay and stripped.startswith("[") and stripped.endswith("]"):
            break
        if not in_assay:
            continue
        fields = stripped.split(",")
        if name_idx is None:
            for i, col in enumerate(fields):
                if col.strip().lower() == "name":
                    name_idx = i
                    break
            continue
        if len(fields) > name_idx:
            name = fields[name_idx].strip()
            if name.startswith("rs"):
                rsids.add(name)
    return rsids


def _fetch_manifest_rsids(manifest_key: str, *, timeout: float) -> set[str]:
    """Download an Illumina manifest and return the rsID set from its [Assay]."""
    info = ILLUMINA_MANIFEST_URLS[manifest_key]
    url = info["url"]
    print(f"  downloading {info['chip_name']} manifest", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        payload = resp.read()
    if info["kind"] == "zip":
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                raise RuntimeError(f"no CSV inside manifest zip from {url}")
            text = zf.read(csv_names[0]).decode("utf-8", errors="replace")
    else:
        text = payload.decode("utf-8", errors="replace")
    rsids = _extract_rsids_from_manifest_csv(text)
    if not rsids:
        raise RuntimeError(
            f"manifest from {url} yielded zero rsIDs — column layout may have changed"
        )
    print(f"  extracted {len(rsids):,} rsIDs from {manifest_key}", file=sys.stderr)
    return rsids


def _stream_dbsnp_filtered(
    url: str, rsid_set: set[str], out_path: Path, *, timeout: float
) -> int:
    """Stream a dbSNP VCF and write a 5-col TSV.gz limited to rsids in the set.

    Returns the number of rows written. Cleans up the .part on any failure.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    print(f"  streaming {url}", file=sys.stderr)
    completed = False
    written = 0
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            with gzip.open(resp, "rb") as in_fh, gzip.open(tmp, "wt") as out_fh:
                out_fh.write("# rsid\tchrom\tpos\tref\talt\n")
                for raw in in_fh:
                    line = raw.decode("utf-8", errors="replace")
                    if line.startswith("#"):
                        continue
                    parts = line.rstrip("\n").split("\t", 7)
                    if len(parts) < 5:
                        continue
                    chrom, pos, rsid, ref, alt = parts[0], parts[1], parts[2], parts[3], parts[4]
                    if rsid not in rsid_set:
                        continue
                    first_alt = alt.split(",")[0]
                    if len(ref) != 1 or len(first_alt) != 1:
                        continue
                    out_fh.write(f"{rsid}\t{chrom}\t{pos}\t{ref}\t{first_alt}\n")
                    written += 1
        tmp.rename(out_path)
        completed = True
        print(f"  wrote {out_path} ({written:,} rows)", file=sys.stderr)
        return written
    finally:
        if not completed and tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _build_chip_union(build: str, out_path: Path) -> None:
    """Fetch both Illumina manifests + dbSNP, write the joined chip-union TSV.gz."""
    timeout = _timeout_seconds()
    rsid_union: set[str] = set()
    for key in ILLUMINA_MANIFEST_URLS:
        rsid_union |= _fetch_manifest_rsids(key, timeout=timeout)
    print(f"  chip-union rsID count: {len(rsid_union):,}", file=sys.stderr)
    dbsnp_url = DBSNP_URLS[build]
    written = _stream_dbsnp_filtered(dbsnp_url, rsid_union, out_path, timeout=timeout)
    coverage = (written / len(rsid_union) * 100) if rsid_union else 0.0
    print(
        f"  dbSNP coverage of chip union: {written:,}/{len(rsid_union):,} "
        f"({coverage:.1f}%)",
        file=sys.stderr,
    )


def main(argv: list[str]) -> int:
    args = argv[1:]
    yes = False
    if "--yes" in args:
        yes = True
        args.remove("--yes")
    if not args:
        print(__doc__, file=sys.stderr)
        print("available assets:", ", ".join(SOURCES), file=sys.stderr)
        return 2
    for name in args:
        if name not in SOURCES:
            print(f"unknown asset: {name} (choose from {list(SOURCES)})", file=sys.stderr)
            return 2
        info = SOURCES[name]
        if not yes and not _confirm(name, info):
            print(f"skipped {name}", file=sys.stderr)
            continue
        _build_chip_union(info["build"], ASSETS / info["out"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
