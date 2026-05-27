"""Regression tests for #7: input path positional must be resolvable regardless of flag order."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


def test_extract_tolerates_flag_first(fixtures_dir):
    """sample.bed avoids the .fai build step; the flag-ordering fix is what's under test."""
    a = _run([str(SCRIPTS / "extract.py"),
              str(fixtures_dir / "sample.bed"), "--region", "chr1:50-300"])
    b = _run([str(SCRIPTS / "extract.py"),
              "--region", "chr1:50-300", str(fixtures_dir / "sample.bed")])
    assert a.returncode == 0, a.stderr
    assert b.returncode == 0, b.stderr
    assert a.stdout == b.stdout
    assert "region_a" in a.stdout


def test_convert_tolerates_flag_first(fixtures_dir):
    a = _run([str(SCRIPTS / "convert.py"),
              str(fixtures_dir / "sample.fasta"), "--to", "tsv"])
    b = _run([str(SCRIPTS / "convert.py"),
              "--to", "tsv", str(fixtures_dir / "sample.fasta")])
    assert a.returncode == 0, a.stderr
    assert b.returncode == 0, b.stderr
    assert a.stdout == b.stdout


def test_lookup_tolerates_flag_first(fixtures_dir):
    a = _run([str(SCRIPTS / "lookup.py"),
              str(fixtures_dir / "23andme_sample.txt"), "--rsids", "rs1,rs3"])
    b = _run([str(SCRIPTS / "lookup.py"),
              "--rsids", "rs1,rs3", str(fixtures_dir / "23andme_sample.txt")])
    assert a.returncode == 0, a.stderr
    assert b.returncode == 0, b.stderr
    assert a.stdout == b.stdout


def test_translate_tolerates_flag_first(fixtures_dir):
    a = _run([str(SCRIPTS / "translate.py"),
              str(fixtures_dir / "sample.fasta"), "--frame", "1"])
    b = _run([str(SCRIPTS / "translate.py"),
              "--frame", "1", str(fixtures_dir / "sample.fasta")])
    assert a.returncode == 0, a.stderr
    assert b.returncode == 0, b.stderr
    assert a.stdout == b.stdout


def test_translate_table_flag_interleaved(fixtures_dir):
    """Both value flags (--frame and --table) interleaved around the positional."""
    a = _run([str(SCRIPTS / "translate.py"),
              str(fixtures_dir / "sample.fasta"), "--frame", "1", "--table", "1"])
    b = _run([str(SCRIPTS / "translate.py"),
              "--frame", "1", "--table", "1", str(fixtures_dir / "sample.fasta")])
    assert a.returncode == 0, a.stderr
    assert b.returncode == 0, b.stderr
    assert a.stdout == b.stdout


def test_convert_tolerates_interleaved_flags(fixtures_dir):
    """--columns interleaved before the positional input still resolves."""
    a = _run([str(SCRIPTS / "convert.py"),
              str(fixtures_dir / "sample.vcf"), "--to", "tsv",
              "--columns", "chrom,pos"])
    b = _run([str(SCRIPTS / "convert.py"), "--to", "tsv",
              "--columns", "chrom,pos", str(fixtures_dir / "sample.vcf")])
    assert a.returncode == 0, a.stderr
    assert b.returncode == 0, b.stderr
    assert a.stdout == b.stdout
