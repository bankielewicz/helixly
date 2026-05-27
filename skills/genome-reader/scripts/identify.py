#!/usr/bin/env python3
"""Detect format of a genomics file via magic bytes + extension + header sniff."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import detect_format, die  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] in {"-h", "--help"}:
        print("usage: identify.py <path>", file=sys.stderr)
        return 2
    path = argv[1]
    try:
        info = detect_format(path)
    except FileNotFoundError:
        die(f"no such file: {path}")
    print(json.dumps(info.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
