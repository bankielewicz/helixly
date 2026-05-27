#!/usr/bin/env python3
"""Fetch optional reference assets that are too large to bundle in the skill.

Currently supported:
  rsid_grch37   — rsID → (chrom, pos, ref, alt) map at GRCh37 coords
  rsid_grch38   — same at GRCh38 coords

Sources are dbSNP common-variants VCFs from NCBI. The script prints what it
will do and asks for confirmation before any network call.

Usage:
  python scripts/fetch_assets.py <name> [<name> ...]
  python scripts/fetch_assets.py --yes <name>           # skip confirmation
"""

from __future__ import annotations

import gzip
import sys
import urllib.request
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# These are large dbSNP common-variants VCFs. The script streams them and
# extracts only the rsID/chrom/pos/ref/alt columns, then re-bgzips a small TSV.
# `out` is the full map filename. It lives next to the small bundled stub
# (`rsid_grchNN.tsv.gz`) and is gitignored. convert.py prefers the full map
# if present and falls back to the stub.
SOURCES = {
    "rsid_grch37": {
        "url": "https://ftp.ncbi.nih.gov/snp/organisms/human_9606_b151_GRCh37p13/VCF/common_all_20180423.vcf.gz",
        "out": "rsid_grch37.full.tsv.gz",
        "approx_mb": 1500,
    },
    "rsid_grch38": {
        "url": "https://ftp.ncbi.nih.gov/snp/organisms/human_9606_b151_GRCh38p7/VCF/common_all_20180418.vcf.gz",
        "out": "rsid_grch38.full.tsv.gz",
        "approx_mb": 1500,
    },
}


def _confirm(name: str, info: dict) -> bool:
    print(f"\nasset:  {name}")
    print(f"source: {info['url']}")
    print(f"approx: {info['approx_mb']} MB download (then converted to small TSV)")
    print(f"target: {ASSETS / info['out']}")
    ans = input("proceed? [y/N] ").strip().lower()
    return ans == "y"


def _download_and_filter(url: str, out_path: Path) -> None:
    """Stream the dbSNP VCF and write a 5-column TSV.gz."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    print(f"  downloading {url}", file=sys.stderr)
    with urllib.request.urlopen(url) as resp:
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
                if not rsid.startswith("rs"):
                    continue
                # Take only first alt for the lookup map
                first_alt = alt.split(",")[0]
                if len(ref) != 1 or len(first_alt) != 1:
                    continue
                out_fh.write(f"{rsid}\t{chrom}\t{pos}\t{ref}\t{first_alt}\n")
    tmp.rename(out_path)
    print(f"  wrote {out_path}", file=sys.stderr)


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
        _download_and_filter(info["url"], ASSETS / info["out"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
