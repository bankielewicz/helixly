#!/usr/bin/env python3
"""Convert between supported genomics formats.

Supported targets (refuses anything else):
  FASTA   --to tsv        : id, length, gc, sequence
  FASTQ   --to fasta      : drops qualities
  VCF     --to tsv|csv    : one row per variant, INFO/FORMAT flattened
  BED     --to gff
  GFF     --to bed        (lossy — warns)
  Consumer DNA --to vcf   : uses bundled rsID map (or fetched map)
"""

from __future__ import annotations

import csv
import gzip
import json
import re
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    detect_format, detect_consumer_dna_build, die, iter_consumer_dna,
    open_maybe_gzip, parse_flat_args, warn,
)

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def _gc(seq: str) -> float:
    s = seq.upper()
    if not s:
        return 0.0
    return round(100.0 * (s.count("G") + s.count("C")) / len(s), 3)


def fasta_to_tsv(path: str) -> int:
    w = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    w.writerow(["id", "length", "gc", "sequence"])
    with open_maybe_gzip(path, "rt") as fh:
        cur_id = None
        seq_parts: list[str] = []
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith(">"):
                if cur_id is not None:
                    seq = "".join(seq_parts)
                    w.writerow([cur_id, len(seq), _gc(seq), seq])
                cur_id = line[1:].split()[0]
                seq_parts = []
            else:
                seq_parts.append(line)
        if cur_id is not None:
            seq = "".join(seq_parts)
            w.writerow([cur_id, len(seq), _gc(seq), seq])
    return 0


def fastq_to_fasta(path: str) -> int:
    with open_maybe_gzip(path, "rt") as fh:
        while True:
            h = fh.readline()
            if not h:
                break
            seq = fh.readline().rstrip("\n")
            plus = fh.readline()
            _ = fh.readline()
            if not h.startswith("@"):
                die("not FASTQ: header line does not start with @")
            print(">" + h[1:].rstrip("\n"))
            for i in range(0, len(seq), 70):
                print(seq[i:i + 70])
    return 0


_INT_MISSING = -2147483648  # BCF integer-missing sentinel


def _vcf_gt_strs(v) -> list[str] | None:
    """Per-sample GT strings like '0/1' or '.|.'. Returns None if unavailable."""
    try:
        gts = v.genotypes
    except Exception:
        return None
    if gts is None:
        return None
    out: list[str] = []
    for gt in gts:
        if not gt:
            out.append("./.")
            continue
        phased = bool(gt[-1])
        alleles = gt[:-1]
        sep = "|" if phased else "/"
        out.append(sep.join(str(a) if a >= 0 else "." for a in alleles))
    return out


def _vcf_format_strs(v, key: str, n_samples: int) -> list[str]:
    """Per-sample stringified values for one FORMAT key (non-GT)."""
    try:
        arr = v.format(key)
    except Exception:
        return [""] * n_samples
    if arr is None:
        return [""] * n_samples
    out: list[str] = []
    for si in range(n_samples):
        if si >= len(arr):
            out.append("")
            continue
        val = arr[si]
        if hasattr(val, "__iter__") and not isinstance(val, (str, bytes)):
            parts: list[str] = []
            for x in val:
                if hasattr(x, "decode"):
                    x = x.decode("utf-8")
                if isinstance(x, float) and x != x:
                    continue
                if isinstance(x, int) and x == _INT_MISSING:
                    continue
                parts.append(str(x))
            out.append(",".join(parts))
        else:
            if hasattr(val, "decode"):
                val = val.decode("utf-8")
            if isinstance(val, float) and val != val:
                out.append("")
            elif isinstance(val, int) and val == _INT_MISSING:
                out.append("")
            else:
                out.append(str(val))
    return out


def vcf_to_table(path: str, sep: str, columns: list[str] | None = None) -> int:
    import cyvcf2
    vcf = cyvcf2.VCF(path)
    samples = list(vcf.samples)
    # Parse header text directly — keeps us off cyvcf2 internal APIs that vary by version.
    info_keys: list[str] = []
    format_keys: list[str] = []
    for line in vcf.raw_header.splitlines():
        if line.startswith("##INFO=<"):
            for kv in line[len("##INFO=<"):].rstrip(">").split(","):
                if kv.startswith("ID="):
                    info_keys.append(kv[3:])
                    break
        elif line.startswith("##FORMAT=<"):
            for kv in line[len("##FORMAT=<"):].rstrip(">").split(","):
                if kv.startswith("ID="):
                    format_keys.append(kv[3:])
                    break
    info_keys = sorted(set(info_keys))
    format_keys = sorted(set(format_keys))
    base = ["chrom", "pos", "id", "ref", "alt", "qual", "filter"]
    sample_cols = [f"{s}.{k}" for s in samples for k in format_keys]
    all_cols = base + info_keys + sample_cols
    if columns is not None:
        unknown = [c for c in columns if c not in all_cols]
        if unknown:
            print(
                f"convert: unknown column(s): {','.join(unknown)}",
                file=sys.stderr,
            )
            print(
                f"available columns: {','.join(all_cols)}",
                file=sys.stderr,
            )
            return 2
        out_cols = list(columns)
    else:
        out_cols = all_cols
    w = csv.writer(sys.stdout, delimiter=sep, lineterminator="\n")
    w.writerow(out_cols)
    for v in vcf:
        row_map: dict[str, object] = {
            "chrom": v.CHROM,
            "pos": v.POS,
            "id": v.ID or ".",
            "ref": v.REF or ".",
            "alt": ",".join(v.ALT) if v.ALT else ".",
            "qual": "" if v.QUAL is None else v.QUAL,
            "filter": v.FILTER if v.FILTER is not None else "PASS",
        }
        for k in info_keys:
            val = v.INFO.get(k)
            if isinstance(val, tuple):
                val = ",".join(str(x) for x in val)
            row_map[k] = "" if val is None else val
        if samples and format_keys:
            gt_strs = _vcf_gt_strs(v) if "GT" in format_keys else None
            for k in format_keys:
                if k == "GT":
                    continue
                fvals = _vcf_format_strs(v, k, len(samples))
                for si, s in enumerate(samples):
                    row_map[f"{s}.{k}"] = fvals[si]
            if "GT" in format_keys:
                for si, s in enumerate(samples):
                    if gt_strs is not None and si < len(gt_strs):
                        row_map[f"{s}.GT"] = gt_strs[si]
                    else:
                        row_map[f"{s}.GT"] = "./."
        w.writerow([row_map.get(c, "") for c in out_cols])
    return 0


def bed_to_gff(path: str) -> int:
    print("##gff-version 3")
    with open_maybe_gzip(path, "rt") as fh:
        for i, line in enumerate(fh, 1):
            if not line.strip() or line.startswith("#") or line.startswith("track"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            chrom, start, end = parts[0], int(parts[1]) + 1, int(parts[2])  # BED 0-half-open → GFF 1-closed
            name = parts[3] if len(parts) > 3 else f"region_{i}"
            score = parts[4] if len(parts) > 4 else "."
            strand = parts[5] if len(parts) > 5 else "."
            print("\t".join([chrom, "bed2gff", "region", str(start), str(end),
                             score, strand, ".", f"ID={name}"]))
    warn("BED→GFF conversion: feature type set to 'region'; "
         "BED block fields (cols 7-12) are not represented.")
    return 0


def gff_to_bed(path: str) -> int:
    with open_maybe_gzip(path, "rt") as fh:
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 9:
                continue
            chrom = parts[0]
            start = int(parts[3]) - 1  # GFF 1-closed → BED 0-half-open
            end = int(parts[4])
            attrs = parts[8]
            # GFF3 uses ID=value; GTF uses gene_id "value". Prefer GFF3 ID.
            name = "."
            m = re.search(r'(?:^|;)\s*ID=([^;]+)', attrs)
            if m:
                name = m.group(1).strip()
            else:
                m = re.search(r'gene_id\s+"([^"]+)"', attrs)
                if m:
                    name = m.group(1)
            score = parts[5]
            strand = parts[6]
            print("\t".join([chrom, str(start), str(end), name, score, strand]))
    warn("GFF→BED conversion: feature type and source columns are dropped.")
    return 0


def _load_rsid_map(build: str, override: str | None = None) -> dict[str, tuple[str, int, str, str]]:
    """Returns rsid -> (chrom, pos, ref, alt).

    Resolution order: explicit override, then assets/rsid_<build>.full.tsv.gz
    (written by fetch_assets.py, gitignored), then the bundled stub
    assets/rsid_<build>.tsv.gz."""
    suffix = {"GRCh37": "grch37", "GRCh38": "grch38"}[build]
    if override:
        src = Path(override)
    else:
        full = ASSETS / f"rsid_{suffix}.full.tsv.gz"
        stub = ASSETS / f"rsid_{suffix}.tsv.gz"
        src = full if full.exists() else stub
    if not src.exists():
        die(f"rsID map for {build} not found at {src}. "
            f"Run: python scripts/fetch_assets.py rsid_{suffix}")
    out: dict[str, tuple[str, int, str, str]] = {}
    opener = gzip.open if str(src).endswith(".gz") else open
    with opener(src, "rt") as fh:
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 5:
                continue
            rsid, chrom, pos, ref, alt = parts[:5]
            out[rsid] = (chrom, int(pos), ref, alt)
    return out


def _genotype_to_alleles(gt: str) -> list[str]:
    # 23andMe stores 2-char genotype (e.g., "AG"); AncestryDNA concatenated pair.
    gt = gt.upper().strip()
    if gt in {"--", "00", ""}:
        return []
    return [c for c in gt if c in "ACGTID"]


def consumer_dna_to_vcf(path: str, build_override: str | None = None,
                        map_override: str | None = None) -> int:
    build = build_override or detect_consumer_dna_build(path) or "GRCh37"
    rsmap = _load_rsid_map(build, override=map_override)
    print("##fileformat=VCFv4.2")
    print(f"##source=genome-reader/consumer_dna_to_vcf")
    print(f"##reference={build}")
    print("##FORMAT=<ID=GT,Number=1,Type=String,Description=\"Genotype\">")
    print("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE")
    unmapped = 0
    emitted = 0
    for rsid, chrom, pos, genotype in iter_consumer_dna(path):
        info = rsmap.get(rsid)
        if not info:
            unmapped += 1
            continue
        ref_chrom, ref_pos, ref, alt = info
        alleles = _genotype_to_alleles(genotype)
        if not alleles:
            continue
        # Build VCF GT field
        gt_parts: list[str] = []
        for a in alleles:
            if a == ref:
                gt_parts.append("0")
            elif a == alt:
                gt_parts.append("1")
            else:
                gt_parts.append(".")
        gt = "/".join(gt_parts) if gt_parts else "./."
        print("\t".join([ref_chrom, str(ref_pos), rsid, ref, alt, ".", "PASS", ".", "GT", gt]))
        emitted += 1
    warn(f"emitted {emitted} variants; {unmapped} rsIDs not in {build} map")
    return 0


REFUSAL_MSG = (
    "convert: unsupported conversion. Supported targets:\n"
    "  fasta --to tsv\n"
    "  fastq --to fasta\n"
    "  vcf   --to tsv|csv\n"
    "  bed   --to gff\n"
    "  gff   --to bed\n"
    "  consumer_dna --to vcf"
)


def main(argv: list[str]) -> int:
    path, flags = parse_flat_args(
        argv[1:], {"--to", "--build", "--rsid-map", "--columns"}
    )
    if path is None or "--to" not in flags:
        print(
            "usage: convert.py <input> --to <format> "
            "[--build GRCh37|GRCh38] [--columns c1,c2,...]",
            file=sys.stderr,
        )
        return 2
    target = flags["--to"].lower()
    build_override = flags.get("--build")
    map_override = flags.get("--rsid-map")
    columns: list[str] | None = None
    if "--columns" in flags:
        columns = [c.strip() for c in flags["--columns"].split(",") if c.strip()]
        if not columns:
            print("convert: --columns requires a non-empty comma list", file=sys.stderr)
            return 2
    try:
        info = detect_format(path)
    except FileNotFoundError:
        die(f"no such file: {path}")
    src = info.format
    if src == "fasta" and target == "tsv":
        return fasta_to_tsv(path)
    if src == "fastq" and target == "fasta":
        return fastq_to_fasta(path)
    if src == "vcf" and target in {"tsv", "csv"}:
        return vcf_to_table(path, "\t" if target == "tsv" else ",", columns=columns)
    if columns is not None:
        print("convert: --columns is only supported for VCF --to tsv|csv", file=sys.stderr)
        return 2
    if src == "bed" and target in {"gff", "gff3"}:
        return bed_to_gff(path)
    if src in {"gff", "gtf"} and target == "bed":
        return gff_to_bed(path)
    if src.startswith("consumer_dna:") and target == "vcf":
        return consumer_dna_to_vcf(path, build_override, map_override)
    print(REFUSAL_MSG, file=sys.stderr)
    print(f"requested: {src} --to {target}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
