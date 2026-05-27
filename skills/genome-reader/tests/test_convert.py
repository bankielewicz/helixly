"""Conversion correctness: lossless round trips where possible, plus the refusal path."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, **kw)


def test_fasta_to_tsv(fixtures_dir):
    p = _run([str(SCRIPTS / "convert.py"), str(fixtures_dir / "sample.fasta"), "--to", "tsv"])
    assert p.returncode == 0
    rows = [r.split("\t") for r in p.stdout.strip().splitlines()]
    header, *body = rows
    assert header == ["id", "length", "gc", "sequence"]
    assert len(body) == 3
    # seq3 is pure GC
    seq3 = next(r for r in body if r[0] == "seq3")
    assert float(seq3[2]) == 100.0


def test_fastq_to_fasta(fixtures_dir):
    p = _run([str(SCRIPTS / "convert.py"), str(fixtures_dir / "sample.fastq"), "--to", "fasta"])
    assert p.returncode == 0
    # 4 reads → 4 FASTA records
    assert p.stdout.count(">") == 4
    assert "ACGTACGTACGT" in p.stdout


def test_vcf_to_tsv(fixtures_dir):
    p = _run([str(SCRIPTS / "convert.py"), str(fixtures_dir / "sample.vcf"), "--to", "tsv"])
    assert p.returncode == 0
    lines = p.stdout.strip().splitlines()
    assert lines[0].startswith("chrom\tpos\tid\tref\talt")
    # 6 data rows
    assert len(lines) == 7


def test_bed_to_gff(fixtures_dir):
    p = _run([str(SCRIPTS / "convert.py"), str(fixtures_dir / "sample.bed"), "--to", "gff"])
    assert p.returncode == 0
    assert "##gff-version 3" in p.stdout
    # 3 data rows
    assert sum(1 for ln in p.stdout.splitlines() if ln and not ln.startswith("#")) == 3
    # 0-based BED 0..100 → 1-based GFF 1..100
    assert "1\t100\t" in p.stdout


def test_gff_to_bed(fixtures_dir):
    p = _run([str(SCRIPTS / "convert.py"), str(fixtures_dir / "sample.gff"), "--to", "bed"])
    assert p.returncode == 0
    # GFF 1..100 → BED 0..100
    assert "chr1\t0\t100" in p.stdout


def test_consumer_dna_to_vcf(fixtures_dir):
    p = _run([
        str(SCRIPTS / "convert.py"),
        str(fixtures_dir / "23andme_sample.txt"),
        "--to", "vcf",
        "--rsid-map", str(fixtures_dir / "rsid_test_map.tsv"),
    ])
    assert p.returncode == 0
    lines = [ln for ln in p.stdout.splitlines() if not ln.startswith("#")]
    # 5 rsIDs in input; 3 in the test map → 3 emitted
    assert len(lines) == 3
    # rs1 AG, ref A alt G → GT 0/1
    assert any("rs1" in ln and "0/1" in ln for ln in lines)
    # rs3 GG, ref G alt A → GT 0/0
    assert any("rs3" in ln and "0/0" in ln for ln in lines)


def test_refuses_unsupported_conversion(fixtures_dir):
    p = _run([str(SCRIPTS / "convert.py"), str(fixtures_dir / "sample.fasta"), "--to", "bam"])
    assert p.returncode != 0
    assert "unsupported" in p.stderr.lower() or "supported targets" in p.stderr.lower()


def test_refuses_fastq_to_vcf(fixtures_dir):
    p = _run([str(SCRIPTS / "convert.py"), str(fixtures_dir / "sample.fastq"), "--to", "vcf"])
    assert p.returncode != 0
