"""Tests for #24: extract.py --region support for consumer DNA exports.

Region filtering on 23andMe/AncestryDNA/MyHeritage files emits each genotyped
SNP whose position falls in the 1-based inclusive window, as a 4-column TSV
(rsid, chrom, pos, genotype) with no header — matching extract.py's
raw-passthrough convention for BED/GFF/BAM.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
EXTRACT = SCRIPTS / "extract.py"


def _run(path: Path, region: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(EXTRACT), str(path), "--region", region],
        capture_output=True, text=True,
    )


def _rows(stdout: str) -> list[list[str]]:
    return [ln.split("\t") for ln in stdout.splitlines() if ln]


def test_extract_consumer_dna_in_range(fixtures_dir):
    fx = fixtures_dir / "23andme_regions.txt"
    res = _run(fx, "1:100-900")
    assert res.returncode == 0, res.stderr
    rows = _rows(res.stdout)
    # rs100/rs200/rs300 are in [100,900]; rs400 (pos 1500) is not.
    assert [r[0] for r in rows] == ["rs100", "rs200", "rs300"]
    # Column order preserved: rsid, chrom, pos, genotype.
    assert rows[0] == ["rs100", "1", "100", "AG"]


def test_extract_consumer_dna_out_of_range(fixtures_dir):
    fx = fixtures_dir / "23andme_regions.txt"
    res = _run(fx, "1:10000-20000")
    assert res.returncode == 0, res.stderr
    assert res.stdout == ""


def test_extract_consumer_dna_invalid_chrom(fixtures_dir):
    fx = fixtures_dir / "23andme_regions.txt"
    res = _run(fx, "ZZ:1-100000")
    assert res.returncode == 0, res.stderr
    assert res.stdout == ""


def test_extract_consumer_dna_x_chromosome(fixtures_dir):
    fx = fixtures_dir / "23andme_regions.txt"
    res = _run(fx, "X:1000-2500")
    assert res.returncode == 0, res.stderr
    rows = _rows(res.stdout)
    # Only rsX1 (pos 2000); rsX2 (3000) is out of range. Exact chrom match: no
    # autosomal rows leak in despite sharing positions.
    assert rows == [["rsX1", "X", "2000", "AA"]]


def test_extract_consumer_dna_mt_chromosome(fixtures_dir):
    fx = fixtures_dir / "23andme_regions.txt"
    res = _run(fx, "MT:1-100")
    assert res.returncode == 0, res.stderr
    rows = _rows(res.stdout)
    # Only rsMT1 (pos 50); rsMT2 (150) is out of range.
    assert rows == [["rsMT1", "MT", "50", "TT"]]


def test_extract_consumer_dna_no_call_included(fixtures_dir):
    fx = fixtures_dir / "23andme_regions.txt"
    res = _run(fx, "1:1400-1600")
    assert res.returncode == 0, res.stderr
    rows = _rows(res.stdout)
    # In-range no-call SNP is emitted with its genotype preserved verbatim.
    assert rows == [["rs400", "1", "1500", "--"]]


def test_extract_consumer_dna_inclusive_boundaries(fixtures_dir):
    fx = fixtures_dir / "23andme_regions.txt"
    res = _run(fx, "1:100-100")
    assert res.returncode == 0, res.stderr
    rows = _rows(res.stdout)
    # 1-based inclusive: a region equal to a single position returns that SNP.
    assert rows == [["rs100", "1", "100", "AG"]]


def test_extract_consumer_dna_malformed_region(fixtures_dir):
    fx = fixtures_dir / "23andme_regions.txt"
    # Missing the '-' separator -> _parse_region raises -> die() -> exit 2.
    res = _run(fx, "1:100")
    assert res.returncode != 0
    assert "chrom:start-end" in res.stderr
