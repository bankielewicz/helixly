#!/usr/bin/env python3
"""Extract a genomic window from FASTA/VCF/BAM/GFF/GTF.

Region syntax: chrom:start-end (1-based, inclusive)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    detect_format, die, index_or_build, open_maybe_gzip, parse_flat_args,
)


def _parse_region(s: str) -> tuple[str, int, int]:
    if ":" not in s or "-" not in s.split(":", 1)[1]:
        raise ValueError(f"region must be chrom:start-end, got {s!r}")
    chrom, span = s.split(":", 1)
    a, b = span.split("-", 1)
    return chrom, int(a), int(b)


def extract_fasta(path: str, chrom: str, start: int, end: int) -> int:
    import pyfaidx
    index_or_build(path, "fasta")
    fa = pyfaidx.Fasta(path)
    if chrom not in fa:
        die(f"chromosome {chrom!r} not in FASTA index")
    # pyfaidx uses 1-based inclusive when sliced with .get_seq
    seq = fa.get_seq(chrom, start, end)
    print(f">{chrom}:{start}-{end}")
    s = str(seq)
    for i in range(0, len(s), 70):
        print(s[i:i + 70])
    return 0


def extract_vcf(path: str, chrom: str, start: int, end: int) -> int:
    import cyvcf2
    index_or_build(path, "vcf")
    vcf = cyvcf2.VCF(path)
    sys.stdout.write(vcf.raw_header)
    region = f"{chrom}:{start}-{end}"
    for v in vcf(region):
        sys.stdout.write(str(v))
    return 0


def extract_bam(path: str, chrom: str, start: int, end: int) -> int:
    import pysam
    index_or_build(path, "bam")
    af = pysam.AlignmentFile(path, "rb")
    # 0-based half-open for pysam.fetch; spec says 1-based inclusive input
    for read in af.fetch(chrom, start - 1, end):
        print(read.to_string())
    af.close()
    return 0


def extract_intervals(path: str, chrom: str, start: int, end: int, fmt: str) -> int:
    with open_maybe_gzip(path, "rt") as fh:
        for line in fh:
            if not line.strip() or line.startswith("#") or line.startswith("track"):
                continue
            parts = line.rstrip("\n").split("\t")
            if fmt == "bed":
                if len(parts) < 3:
                    continue
                c, s, e = parts[0], int(parts[1]), int(parts[2])
                # BED is 0-based half-open
                if c == chrom and not (e <= start - 1 or s >= end):
                    sys.stdout.write(line)
            else:
                if len(parts) < 9:
                    continue
                c = parts[0]
                s = int(parts[3])
                e = int(parts[4])
                if c == chrom and not (e < start or s > end):
                    sys.stdout.write(line)
    return 0


def main(argv: list[str]) -> int:
    path, flags = parse_flat_args(argv[1:], {"--region"})
    if path is None or "--region" not in flags:
        print("usage: extract.py <path> --region chrom:start-end", file=sys.stderr)
        return 2
    try:
        chrom, start, end = _parse_region(flags["--region"])
    except ValueError as e:
        die(str(e))
    try:
        info = detect_format(path)
    except FileNotFoundError:
        die(f"no such file: {path}")
    fmt = info.format
    if fmt == "fasta":
        return extract_fasta(path, chrom, start, end)
    if fmt == "vcf":
        return extract_vcf(path, chrom, start, end)
    if fmt in {"bam", "cram"}:
        return extract_bam(path, chrom, start, end)
    if fmt in {"bed", "gff", "gtf"}:
        return extract_intervals(path, chrom, start, end, fmt)
    die(f"extract not supported for format: {fmt}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
