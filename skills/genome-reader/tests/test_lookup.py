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


def test_lookup_columns_full_projection(fixtures_dir):
    """Regression for #22: --columns rsid,chrom,pos,genotype emits the 4-tuple from iter_consumer_dna."""
    p = _run([
        str(SCRIPTS / "lookup.py"),
        str(fixtures_dir / "23andme_sample.txt"),
        "--rsids", "rs1,rs3",
        "--columns", "rsid,chrom,pos,genotype",
    ])
    assert p.returncode == 0, p.stderr
    rows = [ln.split("\t") for ln in p.stdout.strip().splitlines()]
    assert rows[0] == ["rsid", "chrom", "pos", "genotype"]
    body = {r[0]: r for r in rows[1:]}
    assert body["rs1"] == ["rs1", "1", "100", "AG"]
    assert body["rs3"] == ["rs3", "2", "500", "GG"]


def test_lookup_columns_subset_and_reorder(fixtures_dir):
    """Regression for #22: --columns honors requested order and supports subsets."""
    p = _run([
        str(SCRIPTS / "lookup.py"),
        str(fixtures_dir / "23andme_sample.txt"),
        "--rsids", "rs2",
        "--columns", "chrom,rsid,genotype",
    ])
    assert p.returncode == 0, p.stderr
    rows = [ln.split("\t") for ln in p.stdout.strip().splitlines()]
    assert rows[0] == ["chrom", "rsid", "genotype"]
    assert rows[1] == ["1", "rs2", "CT"]


def test_lookup_columns_unknown_refuses(fixtures_dir):
    """Regression for #22: unknown column → non-zero exit + stderr lists available columns."""
    p = _run([
        str(SCRIPTS / "lookup.py"),
        str(fixtures_dir / "23andme_sample.txt"),
        "--rsids", "rs1",
        "--columns", "rsid,bogus",
    ])
    assert p.returncode != 0
    assert "bogus" in p.stderr
    assert "available columns" in p.stderr
    for c in ("rsid", "chrom", "pos", "genotype"):
        assert c in p.stderr


def test_lookup_columns_not_tested_row_emits_empty_fields(fixtures_dir):
    """Regression for #22: a rsID absent from input emits rsid + empty chr/pos + genotype 'not_tested'."""
    p = _run([
        str(SCRIPTS / "lookup.py"),
        str(fixtures_dir / "23andme_sample.txt"),
        "--rsids", "rs1,rs_missing",
        "--columns", "rsid,chrom,pos,genotype",
    ])
    assert p.returncode == 0, p.stderr
    rows = [ln.split("\t") for ln in p.stdout.strip().splitlines()]
    body = {r[0]: r for r in rows[1:]}
    assert body["rs1"] == ["rs1", "1", "100", "AG"]
    assert body["rs_missing"] == ["rs_missing", "", "", "not_tested"]
