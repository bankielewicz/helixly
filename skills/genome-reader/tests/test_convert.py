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


def test_vcf_to_tsv_includes_sample_format(fixtures_dir):
    """Regression for #2: VCF→TSV must flatten FORMAT/sample into <sample>.<KEY> columns."""
    p = _run([str(SCRIPTS / "convert.py"), str(fixtures_dir / "sample.vcf"), "--to", "tsv"])
    assert p.returncode == 0
    rows = [r.split("\t") for r in p.stdout.strip().splitlines()]
    header, *body = rows
    assert "S1.GT" in header, f"expected S1.GT in header, got {header}"
    gt_idx = header.index("S1.GT")
    # First data row's S1.GT must be 0/1 per sample.vcf
    assert body[0][gt_idx] == "0/1", f"expected first S1.GT == 0/1, got {body[0][gt_idx]}"
    # Every data row has a non-empty GT
    for r in body:
        assert r[gt_idx], f"unexpected empty S1.GT in row {r}"


def test_vcf_to_tsv_columns_subset(fixtures_dir):
    """Regression for #3: --columns subsets and preserves requested order."""
    p = _run([
        str(SCRIPTS / "convert.py"),
        str(fixtures_dir / "sample.vcf"),
        "--to", "tsv",
        "--columns", "chrom,pos,DP",
    ])
    assert p.returncode == 0, p.stderr
    rows = [r.split("\t") for r in p.stdout.strip().splitlines()]
    assert rows[0] == ["chrom", "pos", "DP"]
    assert len(rows) == 7  # 1 header + 6 data
    assert rows[1][0] == "chr1"
    assert rows[1][1] == "100"
    assert rows[1][2] == "20"


def test_vcf_to_tsv_columns_unknown_refuses(fixtures_dir):
    """Regression for #3: unknown column exits non-zero and reports the name + available list."""
    p = _run([
        str(SCRIPTS / "convert.py"),
        str(fixtures_dir / "sample.vcf"),
        "--to", "tsv",
        "--columns", "chrom,bogus",
    ])
    assert p.returncode != 0
    assert "bogus" in p.stderr
    assert "available columns" in p.stderr
    # The available list must mention real columns, including S1.GT (issue #2 introduces them)
    assert "S1.GT" in p.stderr
    assert "DP" in p.stderr


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
    # GFF3 ID= attribute resolves to the gene/exon name (not the literal "ID=")
    rows = [r.split("\t") for r in p.stdout.strip().splitlines()]
    names = [r[3] for r in rows if len(r) >= 4]
    assert "gene1" in names and "exon1" in names and "exon2" in names


def test_gtf_to_bed_name_extraction(fixtures_dir):
    """Regression for the gene_id parser: previously emitted the literal key."""
    p = _run([str(SCRIPTS / "convert.py"), str(fixtures_dir / "sample.gtf"), "--to", "bed"])
    assert p.returncode == 0
    rows = [r.split("\t") for r in p.stdout.strip().splitlines() if not r.startswith("#")]
    names = [r[3] for r in rows]
    assert names == ["g1", "g1", "g2"], f"expected gene values, got {names}"


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
