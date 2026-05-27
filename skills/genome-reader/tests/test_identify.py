"""Format detection covers every supported extension and the .gz twin."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _identify(path: Path) -> dict:
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "identify.py"), str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def test_fasta_plain(fixtures_dir):
    info = _identify(fixtures_dir / "sample.fasta")
    assert info["format"] == "fasta"
    assert info["compressed"] is False


def test_fasta_gz(fixtures_dir):
    info = _identify(fixtures_dir / "sample.fasta.gz")
    assert info["format"] == "fasta"
    assert info["compressed"] is True


def test_fastq_plain(fixtures_dir):
    info = _identify(fixtures_dir / "sample.fastq")
    assert info["format"] == "fastq"


def test_fastq_gz(fixtures_dir):
    info = _identify(fixtures_dir / "sample.fastq.gz")
    assert info["format"] == "fastq"
    assert info["compressed"] is True


def test_vcf_plain(fixtures_dir):
    info = _identify(fixtures_dir / "sample.vcf")
    assert info["format"] == "vcf"


def test_vcf_gz(fixtures_dir):
    info = _identify(fixtures_dir / "sample.vcf.gz")
    assert info["format"] == "vcf"
    assert info["compressed"] is True
    assert info["index_present"] is True


def test_bam(fixtures_dir):
    info = _identify(fixtures_dir / "sample.bam")
    assert info["format"] == "bam"
    assert info["compressed"] is True


def test_sam(fixtures_dir):
    info = _identify(fixtures_dir / "sample.sam")
    assert info["format"] == "sam"


def test_bed(fixtures_dir):
    info = _identify(fixtures_dir / "sample.bed")
    assert info["format"] == "bed"


def test_bed_gz(fixtures_dir):
    info = _identify(fixtures_dir / "sample.bed.gz")
    assert info["format"] == "bed"
    assert info["compressed"] is True


def test_gff(fixtures_dir):
    info = _identify(fixtures_dir / "sample.gff")
    assert info["format"] == "gff"


def test_gff_gz(fixtures_dir):
    info = _identify(fixtures_dir / "sample.gff.gz")
    assert info["format"] == "gff"


def test_gtf(fixtures_dir):
    info = _identify(fixtures_dir / "sample.gtf")
    assert info["format"] == "gtf"


def test_consumer_23andme(fixtures_dir):
    info = _identify(fixtures_dir / "23andme_sample.txt")
    assert info["format"] == "consumer_dna:23andme"


def test_consumer_ancestry(fixtures_dir):
    info = _identify(fixtures_dir / "ancestry_sample.txt")
    assert info["format"] == "consumer_dna:ancestrydna"


def test_consumer_myheritage(fixtures_dir):
    info = _identify(fixtures_dir / "myheritage_sample.csv")
    assert info["format"] == "consumer_dna:myheritage"
