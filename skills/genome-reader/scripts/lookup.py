#!/usr/bin/env python3
"""Given a consumer DNA export and a list of rsIDs, print TSV: rsid<TAB>genotype.

rsIDs not present in the input file are reported as 'not_tested'.
The rsID list can be a file path (one per line, '#' comments allowed) or a
comma-separated list passed inline.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import detect_format, die, iter_consumer_dna, parse_flat_args  # noqa: E402


def _load_rsids(arg: str) -> list[str]:
    p = Path(arg)
    if p.exists():
        out: list[str] = []
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            out.append(line.split()[0])
        return out
    return [r.strip() for r in arg.split(",") if r.strip()]


def main(argv: list[str]) -> int:
    path, flags = parse_flat_args(argv[1:], {"--rsids"})
    if path is None or "--rsids" not in flags:
        print("usage: lookup.py <consumer_dna_file> --rsids <file_or_csv>", file=sys.stderr)
        return 2
    rsid_arg = flags["--rsids"]
    try:
        info = detect_format(path)
    except FileNotFoundError:
        die(f"no such file: {path}")
    if not info.format.startswith("consumer_dna:"):
        die(f"not a consumer DNA file (detected {info.format})")
    requested = _load_rsids(rsid_arg)
    table: dict[str, str] = {}
    for rsid, _chrom, _pos, genotype in iter_consumer_dna(path):
        table[rsid] = genotype
    sys.stdout.write("rsid\tgenotype\n")
    for r in requested:
        sys.stdout.write(f"{r}\t{table.get(r, 'not_tested')}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
