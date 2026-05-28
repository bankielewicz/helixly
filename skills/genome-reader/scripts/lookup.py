#!/usr/bin/env python3
"""Given a consumer DNA export and a list of rsIDs, print TSV: rsid<TAB>genotype.

rsIDs not present in the input file are reported as 'not_tested'.
The rsID list can be a file path (one per line, '#' comments allowed) or a
comma-separated list passed inline.

Pass --columns to widen the projection. Available columns: rsid, chrom, pos,
genotype. Default output (no --columns) is rsid<TAB>genotype for backward
compatibility. With --columns, rows for not-tested rsIDs emit the rsid plus
empty strings in the remaining columns.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import detect_format, die, iter_consumer_dna, parse_flat_args  # noqa: E402

AVAILABLE_COLUMNS = ("rsid", "chrom", "pos", "genotype")


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
    path, flags = parse_flat_args(argv[1:], {"--rsids", "--columns"})
    if path is None or "--rsids" not in flags:
        print(
            "usage: lookup.py <consumer_dna_file> --rsids <file_or_csv> "
            "[--columns rsid,chrom,pos,genotype]",
            file=sys.stderr,
        )
        return 2
    rsid_arg = flags["--rsids"]
    columns: tuple[str, ...] | None = None
    if "--columns" in flags:
        requested_cols = [c.strip() for c in flags["--columns"].split(",") if c.strip()]
        if not requested_cols:
            print("lookup: --columns requires a non-empty comma list", file=sys.stderr)
            return 2
        unknown = [c for c in requested_cols if c not in AVAILABLE_COLUMNS]
        if unknown:
            print(f"lookup: unknown column(s): {','.join(unknown)}", file=sys.stderr)
            print(f"available columns: {','.join(AVAILABLE_COLUMNS)}", file=sys.stderr)
            return 2
        columns = tuple(requested_cols)
    try:
        info = detect_format(path)
    except FileNotFoundError:
        die(f"no such file: {path}")
    if not info.format.startswith("consumer_dna:"):
        die(f"not a consumer DNA file (detected {info.format})")
    requested = _load_rsids(rsid_arg)
    table: dict[str, tuple[str, str, str]] = {}
    for rsid, chrom, pos, genotype in iter_consumer_dna(path):
        table[rsid] = (chrom, pos, genotype)
    if columns is None:
        sys.stdout.write("rsid\tgenotype\n")
        for r in requested:
            entry = table.get(r)
            genotype = entry[2] if entry is not None else "not_tested"
            sys.stdout.write(f"{r}\t{genotype}\n")
        return 0
    sys.stdout.write("\t".join(columns) + "\n")
    for r in requested:
        entry = table.get(r)
        row = {"rsid": r}
        if entry is not None:
            row["chrom"], row["pos"], row["genotype"] = entry
        else:
            row["chrom"] = ""
            row["pos"] = ""
            row["genotype"] = "not_tested"
        sys.stdout.write("\t".join(row[c] for c in columns) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
