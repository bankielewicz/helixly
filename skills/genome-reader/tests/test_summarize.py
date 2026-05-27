"""Numeric correctness of summarize.py on known-answer fixtures."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _summarize(path: Path) -> dict:
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "summarize.py"), str(path), "--json"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def test_fasta_summary(fixtures_dir):
    # sample.fasta has 3 sequences: lengths 32, 36, 16; total 84.
    # GC: seq1 ACGTACGTACGTACGTACGTACGTACGTACGT -> 16 GC out of 32 = 50%
    #     seq2 GGGGCCCCAAAATTTTGGGGCCCCAAAATTTTNNNN -> 16 GC out of 36 (incl 4 N)
    #     seq3 GCGCGCGCGCGCGCGC -> 16 GC out of 16 = 100%
    # Total GC = 48/84 ~= 57.143%
    s = _summarize(fixtures_dir / "sample.fasta")
    assert s["format"] == "fasta"
    assert s["sequence_count"] == 3
    assert s["total_length"] == 84
    assert s["min_length"] == 16
    assert s["max_length"] == 36
    assert s["ambiguous_bases"] == 4  # the four Ns in seq2
    assert 56 <= s["gc_percent"] <= 58


def test_fastq_summary(fixtures_dir):
    s = _summarize(fixtures_dir / "sample.fastq")
    assert s["format"] == "fastq"
    assert s["read_count"] == 4
    assert s["min_length"] == 12
    assert s["max_length"] == 12
    assert s["phred_encoding"] == "Phred+33"


def test_vcf_summary(fixtures_dir):
    s = _summarize(fixtures_dir / "sample.vcf")
    assert s["format"] == "vcf"
    assert s["variant_count"] == 6
    assert s["snv"] == 3
    # GA->G, A->AT, ACGT->A are 3 indels
    assert s["indel"] == 3
    assert s["per_chromosome"]["chr1"] == 4
    assert s["per_chromosome"]["chr2"] == 2
    assert s["pass_count"] == 5
    assert s["filtered_count"] == 1
    assert s["samples"] == ["S1"]


def test_bam_summary(fixtures_dir):
    s = _summarize(fixtures_dir / "sample.bam")
    assert s["format"] == "bam"
    assert s["read_count"] == 5
    assert s["mapped"] == 4
    assert s["unmapped"] == 1
    # r4 is flagged duplicate (1024 flag)
    assert s["duplicate_rate"] > 0


def test_bed_summary(fixtures_dir):
    s = _summarize(fixtures_dir / "sample.bed")
    assert s["format"] == "bed"
    assert s["feature_count"] == 3
    # spans: 100 + 150 + 1000
    assert s["span_per_chromosome"]["chr1"] == 250
    assert s["span_per_chromosome"]["chr2"] == 1000


def test_gff_summary(fixtures_dir):
    s = _summarize(fixtures_dir / "sample.gff")
    assert s["format"] == "gff"
    assert s["feature_count"] == 4
    assert s["feature_types"]["gene"] == 2
    assert s["feature_types"]["exon"] == 2


def test_consumer_dna_summary(fixtures_dir):
    s = _summarize(fixtures_dir / "23andme_sample.txt")
    assert s["format"] == "consumer_dna:23andme"
    assert s["snp_count"] == 5
    assert s["build"] == "GRCh37"
    # rs4 is "--" → no-call
    assert s["no_call_rate"] > 0
