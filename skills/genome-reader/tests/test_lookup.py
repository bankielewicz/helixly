"""rsID lookup on consumer DNA: hits, misses, and 'not_tested' markers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


def test_lookup_inline(fixtures_dir):
    p = _run([
        str(SCRIPTS / "lookup.py"),
        str(fixtures_dir / "23andme_sample.txt"),
        "--rsids", "rs1,rs3,rs_missing",
    ])
    assert p.returncode == 0
    lines = p.stdout.strip().splitlines()
    assert lines[0] == "rsid\tgenotype"
    table = dict(line.split("\t") for line in lines[1:])
    assert table["rs1"] == "AG"
    assert table["rs3"] == "GG"
    assert table["rs_missing"] == "not_tested"


def test_lookup_from_file(fixtures_dir, tmp_path):
    rs_file = tmp_path / "rsids.txt"
    rs_file.write_text("# my rsIDs\nrs2\nrs9999\nrs_missing\n")
    p = _run([
        str(SCRIPTS / "lookup.py"),
        str(fixtures_dir / "23andme_sample.txt"),
        "--rsids", str(rs_file),
    ])
    assert p.returncode == 0
    table = dict(line.split("\t") for line in p.stdout.strip().splitlines()[1:])
    assert table["rs2"] == "CT"
    assert table["rs9999"] == "AA"
    assert table["rs_missing"] == "not_tested"


def test_lookup_rejects_non_consumer_dna(fixtures_dir):
    p = _run([
        str(SCRIPTS / "lookup.py"),
        str(fixtures_dir / "sample.fasta"),
        "--rsids", "rs1",
    ])
    assert p.returncode != 0
