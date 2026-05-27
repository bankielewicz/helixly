"""Shared helpers for genome-reader scripts."""

from __future__ import annotations

import gzip
import io
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterable, Optional

GZIP_MAGIC = b"\x1f\x8b"
BAM_MAGIC = b"\x1f\x8b"  # BAM is BGZF, also starts 0x1f 0x8b; disambiguate by content
CRAM_MAGIC = b"CRAM"

FASTA_EXTS = {".fasta", ".fa", ".fna", ".faa", ".ffn", ".frn"}
FASTQ_EXTS = {".fastq", ".fq"}
VCF_EXTS = {".vcf"}
BED_EXTS = {".bed"}
GFF_EXTS = {".gff", ".gff3"}
GTF_EXTS = {".gtf"}
BAM_EXTS = {".bam"}
SAM_EXTS = {".sam"}
CRAM_EXTS = {".cram"}


def is_gzipped(path: str | os.PathLike) -> bool:
    with open(path, "rb") as fh:
        return fh.read(2) == GZIP_MAGIC


def open_maybe_gzip(path: str | os.PathLike, mode: str = "rt") -> IO:
    """Open a file, transparently handling .gz. Always returns the requested mode."""
    if is_gzipped(path):
        return gzip.open(path, mode)
    return open(path, mode)


def _strip_compound_suffix(name: str) -> tuple[str, bool]:
    """Return (base_ext, compressed) where compressed reflects a .gz suffix."""
    p = Path(name)
    if p.suffix == ".gz":
        return p.with_suffix("").suffix.lower(), True
    return p.suffix.lower(), False


def _sniff_header(path: str | os.PathLike, n: int = 4096) -> bytes:
    if is_gzipped(path):
        with gzip.open(path, "rb") as fh:
            return fh.read(n)
    with open(path, "rb") as fh:
        return fh.read(n)


def _looks_like_bam(path: str | os.PathLike) -> bool:
    # BAM is BGZF with magic block; after gunzipping the first block, the first
    # 4 bytes are "BAM\1".
    if not is_gzipped(path):
        return False
    try:
        with gzip.open(path, "rb") as fh:
            return fh.read(4) == b"BAM\1"
    except OSError:
        return False


def _looks_like_cram(path: str | os.PathLike) -> bool:
    with open(path, "rb") as fh:
        return fh.read(4) == CRAM_MAGIC


def _consumer_dna_kind(header: bytes) -> Optional[str]:
    """Return '23andme', 'ancestrydna', 'myheritage', or None."""
    text = header.decode("utf-8", errors="replace")
    low = text.lower()
    if "23andme" in low:
        return "23andme"
    if "ancestrydna" in low or "ancestry.com" in low:
        return "ancestrydna"
    if "myheritage" in low:
        return "myheritage"
    # MyHeritage CSV header signature
    if text.lstrip().upper().startswith("RSID,CHROMOSOME,POSITION,RESULT"):
        return "myheritage"
    # 23andMe column header in a TSV without a # comment block
    first_line = text.lstrip().splitlines()[0] if text.strip() else ""
    if first_line.startswith("# rsid") or first_line.startswith("rsid\tchromosome"):
        # Could be 23andMe or AncestryDNA — both use the same column order.
        # Genotype field shape disambiguates: AncestryDNA stores two columns
        # (allele1, allele2); 23andMe stores a single 2-character genotype.
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) == 4:
                return "23andme"
            if len(parts) == 5:
                return "ancestrydna"
            break
    return None


@dataclass
class FormatInfo:
    format: str
    compressed: bool
    size_bytes: int
    index_present: bool
    record_count_estimate: Optional[int]

    def to_dict(self) -> dict:
        # Key order matches the genome-reader spec §6.1.
        return {
            "format": self.format,
            "compressed": self.compressed,
            "record_count_estimate": self.record_count_estimate,
            "size_bytes": self.size_bytes,
            "index_present": self.index_present,
        }


def detect_format(path: str | os.PathLike) -> FormatInfo:
    """Detect genomics file format. Never loads the full file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    size = p.stat().st_size
    base_ext, compressed = _strip_compound_suffix(p.name)

    # CRAM has its own magic, no gzip
    if _looks_like_cram(p) or base_ext in CRAM_EXTS:
        return FormatInfo("cram", False, size, _has_index(p, "cram"), _estimate_records(p, "cram"))

    # BAM (BGZF + BAM\1)
    if base_ext in BAM_EXTS or _looks_like_bam(p):
        return FormatInfo("bam", True, size, _has_index(p, "bam"), _estimate_records(p, "bam"))

    # SAM (text)
    if base_ext in SAM_EXTS:
        return FormatInfo("sam", compressed, size, False, _estimate_records(p, "sam"))

    header = _sniff_header(p)

    # VCF
    if base_ext in VCF_EXTS or header.startswith(b"##fileformat=VCF"):
        return FormatInfo("vcf", compressed, size, _has_index(p, "vcf"), _estimate_records(p, "vcf"))

    # GFF / GTF
    if base_ext in GFF_EXTS or header.startswith(b"##gff-version"):
        return FormatInfo("gff", compressed, size, False, _estimate_records(p, "gff"))
    if base_ext in GTF_EXTS:
        return FormatInfo("gtf", compressed, size, False, _estimate_records(p, "gtf"))

    # Consumer DNA must precede generic BED detection since they're also TSV
    consumer = _consumer_dna_kind(header)
    if consumer:
        return FormatInfo(f"consumer_dna:{consumer}", compressed, size, False,
                          _estimate_records(p, "consumer_dna"))

    # FASTA / FASTQ by first byte
    text_head = header.lstrip()
    if text_head.startswith(b">") or base_ext in FASTA_EXTS:
        return FormatInfo("fasta", compressed, size, _has_index(p, "fasta"),
                          _estimate_records(p, "fasta"))
    if text_head.startswith(b"@") or base_ext in FASTQ_EXTS:
        # @ is also SAM header — but SAM was handled above by extension.
        # For unambiguous detection, also check for 4-line FASTQ pattern.
        if _is_fastq_pattern(header):
            return FormatInfo("fastq", compressed, size, False, _estimate_records(p, "fastq"))

    # BED — TSV with 3+ columns, first column looks like a chromosome
    if base_ext in BED_EXTS:
        return FormatInfo("bed", compressed, size, _has_index(p, "bed"), _estimate_records(p, "bed"))

    return FormatInfo("unknown", compressed, size, False, None)


def _is_fastq_pattern(header: bytes) -> bool:
    try:
        text = header.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return False
    lines = text.splitlines()
    if len(lines) < 4:
        return False
    return lines[0].startswith("@") and lines[2].startswith("+")


def _has_index(path: Path, kind: str) -> bool:
    if kind == "fasta":
        return Path(str(path) + ".fai").exists()
    if kind == "vcf":
        return Path(str(path) + ".tbi").exists() or Path(str(path) + ".csi").exists()
    if kind == "bam":
        return Path(str(path) + ".bai").exists() or Path(str(path) + ".csi").exists()
    if kind == "cram":
        return Path(str(path) + ".crai").exists()
    if kind == "bed":
        return Path(str(path) + ".tbi").exists()
    return False


def _estimate_records(path: Path, kind: str) -> Optional[int]:
    """Estimate record count without loading the full file.

    For text formats: sample the first ~64KB, count records there, then
    extrapolate by total file size. Returns None when we can't tell cheaply
    (e.g., BAM, CRAM — accurate count needs index or full scan)."""
    if kind in {"bam", "cram"}:
        return None  # honest about uncertainty; summarize.py reports exact via index
    try:
        sample_size = 65536
        if is_gzipped(path):
            with gzip.open(path, "rb") as fh:
                sample = fh.read(sample_size)
            sample_records = _count_records_in_buffer(sample, kind)
            if not sample or sample_records == 0:
                return 0
            total_decomp = _estimate_decompressed_size(path)
            ratio = max(1.0, total_decomp / max(1, len(sample)))
            return int(sample_records * ratio)
        else:
            with open(path, "rb") as fh:
                sample = fh.read(sample_size)
            size = path.stat().st_size
            sample_records = _count_records_in_buffer(sample, kind)
            if not sample or sample_records == 0:
                return 0
            if size <= len(sample):
                return sample_records
            return int(sample_records * (size / len(sample)))
    except OSError:
        return None


def _estimate_decompressed_size(path: Path) -> int:
    """Read just the last 4 bytes of a gzip file — that's the ISIZE field (mod 2^32)."""
    try:
        with open(path, "rb") as fh:
            fh.seek(-4, os.SEEK_END)
            buf = fh.read(4)
        return int.from_bytes(buf, "little")
    except OSError:
        return path.stat().st_size * 4  # rough fallback


def _count_records_in_buffer(buf: bytes, kind: str) -> int:
    try:
        text = buf.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return 0
    if kind == "fasta":
        return text.count("\n>") + (1 if text.startswith(">") else 0)
    if kind == "fastq":
        # 4 lines per record
        lines = [ln for ln in text.splitlines() if ln]
        return max(0, len(lines) // 4)
    if kind == "vcf":
        return sum(1 for ln in text.splitlines() if ln and not ln.startswith("#"))
    if kind in {"bed", "gff", "gtf"}:
        return sum(1 for ln in text.splitlines() if ln and not ln.startswith("#") and not ln.startswith("track"))
    if kind == "consumer_dna":
        return sum(1 for ln in text.splitlines() if ln and not ln.startswith("#") and not ln.lower().startswith("rsid"))
    if kind == "sam":
        return sum(1 for ln in text.splitlines() if ln and not ln.startswith("@"))
    return 0


def iter_consumer_dna(path: str | os.PathLike) -> Iterable[tuple[str, str, str, str]]:
    """Yield (rsid, chrom, pos, genotype) tuples from any supported consumer DNA file."""
    header_bytes = _sniff_header(path)
    kind = _consumer_dna_kind(header_bytes)
    if kind is None:
        raise ValueError(f"Not a recognized consumer DNA file: {path}")
    if kind == "myheritage":
        with open_maybe_gzip(path, "rt") as fh:
            first = True
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(",")
                if first:
                    first = False
                    if parts[0].upper() == "RSID":
                        continue
                if len(parts) < 4:
                    continue
                rsid, chrom, pos, genotype = parts[0], parts[1], parts[2], parts[3]
                yield rsid.strip('"'), chrom.strip('"'), pos.strip('"'), genotype.strip('"')
    elif kind == "ancestrydna":
        with open_maybe_gzip(path, "rt") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if parts[0].lower() == "rsid":
                    continue
                if len(parts) < 5:
                    continue
                rsid, chrom, pos, a1, a2 = parts[:5]
                yield rsid, chrom, pos, a1 + a2
    else:  # 23andme
        with open_maybe_gzip(path, "rt") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if parts[0].lower() == "rsid":
                    continue
                if len(parts) < 4:
                    continue
                yield parts[0], parts[1], parts[2], parts[3]


def detect_consumer_dna_build(path: str | os.PathLike) -> Optional[str]:
    """Look in header comments for 'build 37'/'build 38'/'GRCh37'/'GRCh38'."""
    header_text = _sniff_header(path).decode("utf-8", errors="replace").lower()
    if "build 38" in header_text or "grch38" in header_text:
        return "GRCh38"
    if "build 37" in header_text or "grch37" in header_text:
        return "GRCh37"
    return None


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def phred_offset(min_qchar: int, max_qchar: int) -> tuple[int, str]:
    """Infer Phred encoding offset from the observed qual-char range.

    Phred+33 uses chars in [33, 74]; Phred+64 uses chars in [59, 104]. The
    overlap is [59, 74], so deciding on `min_qchar` alone misclassifies a
    high-quality Phred+33 file (every char >= 59) as Phred+64. Inspect both
    ends and default the overlap to Phred+33 (modern Illumina), with a
    stderr note when the range cannot be resolved unambiguously.
    """
    if max_qchar > 74:
        return 64, "Phred+64"
    if min_qchar < 59:
        return 33, "Phred+33"
    warn(
        f"FASTQ quality char range [{min_qchar}, {max_qchar}] falls in the "
        "Phred+33/Phred+64 overlap; assuming Phred+33"
    )
    return 33, "Phred+33"


def die(msg: str, code: int = 2) -> "NoReturn":
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def index_or_build(path: str | os.PathLike, kind: str) -> Optional[str]:
    """Make sure the appropriate index exists; build it if missing and writable.

    Returns the index path on success, or None if no index applies.
    Raises RuntimeError if an index is required but cannot be created.
    """
    p = Path(path)
    if kind == "fasta":
        idx = Path(str(p) + ".fai")
        if not idx.exists():
            import pysam  # local import — heavy
            try:
                pysam.faidx(str(p))
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"could not build FASTA index for {p}: {e}") from e
        return str(idx)
    if kind == "vcf":
        if not is_gzipped(p):
            raise RuntimeError(f"VCF must be bgzipped to index: {p}")
        idx = Path(str(p) + ".tbi")
        if not idx.exists():
            import pysam
            try:
                pysam.tabix_index(str(p), preset="vcf", force=False, keep_original=True)
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"could not build VCF index for {p}: {e}") from e
        return str(idx)
    if kind == "bam":
        idx = Path(str(p) + ".bai")
        if not idx.exists():
            import pysam
            try:
                pysam.index(str(p))
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"could not build BAM index for {p}: {e}") from e
        return str(idx)
    return None
