#!/usr/bin/env python3
"""Translate DNA (FASTA) to protein.

Frames: 1, 2, 3, -1, -2, -3, all. Stop codons render as '*'.
--table selects an NCBI genetic code (1, 2, 4, 5, 11). Default 1.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import detect_format, die, open_maybe_gzip  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "assets"
COMPLEMENT = str.maketrans("ACGTUNacgtun", "TGCAANtgcaan")


def _load_table(table_id: str) -> dict[str, str]:
    data = json.loads((ASSETS / "genetic_codes.json").read_text())
    if table_id not in data:
        die(f"unknown genetic code table: {table_id} (supported: {sorted(data.keys())})")
    base = dict(data["1"]["table"])
    if table_id != "1":
        for k, v in data[table_id].get("overrides", {}).items():
            base[k] = v
    return base


def _translate(seq: str, table: dict[str, str]) -> str:
    seq = seq.upper().replace("U", "T")
    out = []
    for i in range(0, len(seq) - 2, 3):
        codon = seq[i:i + 3]
        if len(codon) < 3:
            break
        out.append(table.get(codon, "X"))
    return "".join(out)


def _reverse_complement(seq: str) -> str:
    return seq.translate(COMPLEMENT)[::-1]


def _frames(arg: str) -> list[int]:
    if arg == "all":
        return [1, 2, 3, -1, -2, -3]
    f = int(arg)
    if f not in {1, 2, 3, -1, -2, -3}:
        die("--frame must be one of 1, 2, 3, -1, -2, -3, all")
    return [f]


def _iter_fasta(path: str):
    cur_id: str | None = None
    parts: list[str] = []
    with open_maybe_gzip(path, "rt") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith(">"):
                if cur_id is not None:
                    yield cur_id, "".join(parts)
                cur_id = line[1:].split()[0]
                parts = []
            else:
                parts.append(line)
        if cur_id is not None:
            yield cur_id, "".join(parts)


def main(argv: list[str]) -> int:
    args = argv[1:]
    if "--frame" not in args or len(args) < 3:
        print("usage: translate.py <fasta> --frame <1|2|3|-1|-2|-3|all> [--table 1]",
              file=sys.stderr)
        return 2
    path = args[0]
    frame_arg = args[args.index("--frame") + 1]
    table_id = "1"
    if "--table" in args:
        table_id = args[args.index("--table") + 1]
    try:
        info = detect_format(path)
    except FileNotFoundError:
        die(f"no such file: {path}")
    if info.format != "fasta":
        die(f"translate requires FASTA, got {info.format}")
    frames = _frames(frame_arg)
    table = _load_table(table_id)
    for seq_id, seq in _iter_fasta(path):
        for f in frames:
            if f > 0:
                s = seq[f - 1:]
            else:
                s = _reverse_complement(seq)[(-f) - 1:]
            protein = _translate(s, table)
            print(f">{seq_id}|frame={f}|table={table_id}")
            for i in range(0, len(protein), 70):
                print(protein[i:i + 70])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
