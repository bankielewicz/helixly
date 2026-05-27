"""Synthesizes the binary/indexed fixtures the test suite expects.

Plain-text fixtures are checked in under tests/fixtures/. Binary, gzipped,
and indexed variants are derived from those at first-run time so we don't
have to track binary blobs in the tree.
"""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def _gz(src: Path, dst: Path) -> None:
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    with open(src, "rb") as in_fh, gzip.open(dst, "wb") as out_fh:
        shutil.copyfileobj(in_fh, out_fh)


@pytest.fixture(scope="session", autouse=True)
def materialize_fixtures():
    """Build .gz, .bam, and indexed variants from the plain-text checked-in fixtures."""
    # .gz pairs for every plain text fixture that has a compressed twin in scope.
    # VCF is handled separately below because the tests expect it bgzipped + tabix-indexed.
    for name in (
        "sample.fasta",
        "sample.fastq",
        "sample.bed",
        "sample.gff",
    ):
        src = FIX / name
        if src.exists():
            _gz(src, FIX / (name + ".gz"))

    # BAM from SAM via pysam
    sam = FIX / "sample.sam"
    bam = FIX / "sample.bam"
    if sam.exists() and (not bam.exists() or bam.stat().st_mtime < sam.stat().st_mtime):
        import pysam
        with pysam.AlignmentFile(str(sam), "r") as in_af:
            with pysam.AlignmentFile(str(bam), "wb", template=in_af) as out_af:
                for r in in_af:
                    out_af.write(r)
        # index
        try:
            pysam.index(str(bam))
        except Exception:  # noqa: BLE001
            pass

    # bgzipped VCF + tabix index (cyvcf2/pysam need bgzip, not plain gzip)
    vcf = FIX / "sample.vcf"
    if vcf.exists():
        import pysam
        out = FIX / "sample.vcf.gz"
        tbi = FIX / "sample.vcf.gz.tbi"
        needs_rebuild = (
            not out.exists()
            or not tbi.exists()
            or out.stat().st_mtime < vcf.stat().st_mtime
        )
        if needs_rebuild:
            # Stage the .vcf next to where we want the .vcf.gz, then let
            # tabix_index create them in place.
            tmp_src = FIX / "_sample_for_tbi.vcf"
            shutil.copyfile(vcf, tmp_src)
            # Remove any stale outputs from a previous failed run
            for stale in (out, tbi, FIX / "_sample_for_tbi.vcf.gz",
                          FIX / "_sample_for_tbi.vcf.gz.tbi"):
                if stale.exists():
                    stale.unlink()
            pysam.tabix_index(str(tmp_src), preset="vcf", force=True, keep_original=False)
            gz = FIX / "_sample_for_tbi.vcf.gz"
            gz_tbi = FIX / "_sample_for_tbi.vcf.gz.tbi"
            if gz.exists():
                gz.rename(out)
            if gz_tbi.exists():
                gz_tbi.rename(tbi)

    yield


@pytest.fixture
def fixtures_dir() -> Path:
    return FIX
