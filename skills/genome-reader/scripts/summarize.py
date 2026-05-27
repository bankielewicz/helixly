#!/usr/bin/env python3
"""Format-aware summary of a genomics file. Use --json for machine output."""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    FormatInfo, detect_format, detect_consumer_dna_build, die,
    iter_consumer_dna, open_maybe_gzip,
)


def _n50(lengths: list[int]) -> int:
    if not lengths:
        return 0
    s = sorted(lengths, reverse=True)
    total = sum(s)
    cum = 0
    for ln in s:
        cum += ln
        if cum >= total / 2:
            return ln
    return s[-1]


def summarize_fasta(path: str) -> dict[str, Any]:
    lengths: list[int] = []
    gc_total = 0
    base_total = 0
    ambiguous = 0
    with open_maybe_gzip(path, "rt") as fh:
        seq_buf: list[str] = []
        for line in fh:
            if line.startswith(">"):
                if seq_buf:
                    s = "".join(seq_buf).upper()
                    lengths.append(len(s))
                    gc_total += s.count("G") + s.count("C")
                    base_total += len(s)
                    ambiguous += sum(1 for c in s if c not in "ACGTU")
                    seq_buf = []
            else:
                seq_buf.append(line.strip())
        if seq_buf:
            s = "".join(seq_buf).upper()
            lengths.append(len(s))
            gc_total += s.count("G") + s.count("C")
            base_total += len(s)
            ambiguous += sum(1 for c in s if c not in "ACGTU")
    if not lengths:
        return {"format": "fasta", "sequence_count": 0}
    return {
        "format": "fasta",
        "sequence_count": len(lengths),
        "total_length": sum(lengths),
        "min_length": min(lengths),
        "max_length": max(lengths),
        "median_length": int(statistics.median(lengths)),
        "mean_length": round(statistics.fmean(lengths), 2),
        "n50": _n50(lengths),
        "gc_percent": round(100.0 * gc_total / base_total, 3) if base_total else 0.0,
        "ambiguous_bases": ambiguous,
    }


def summarize_fastq(path: str) -> dict[str, Any]:
    lengths: list[int] = []
    qual_sum = 0
    qual_chars = 0
    min_qchar = 255
    max_qchar = 0
    adapter_hits = 0
    sampled = 0
    adapters = ("AGATCGGAAGAGC", "CTGTCTCTTATACA")  # Illumina TruSeq, Nextera
    with open_maybe_gzip(path, "rt") as fh:
        while True:
            h = fh.readline()
            if not h:
                break
            seq = fh.readline().rstrip("\n")
            plus = fh.readline()
            qual = fh.readline().rstrip("\n")
            if not qual:
                break
            lengths.append(len(seq))
            for c in qual:
                v = ord(c)
                qual_sum += v
                qual_chars += 1
                if v < min_qchar:
                    min_qchar = v
                if v > max_qchar:
                    max_qchar = v
            if sampled < 100_000:
                if any(ad in seq for ad in adapters):
                    adapter_hits += 1
                sampled += 1
    if not lengths:
        return {"format": "fastq", "read_count": 0}
    # Phred encoding heuristic: Phred+33 chars in [33,74]; Phred+64 in [59,104].
    if min_qchar < 59:
        encoding = "Phred+33"
        mean_qual = round((qual_sum / qual_chars) - 33, 2)
    else:
        encoding = "Phred+64"
        mean_qual = round((qual_sum / qual_chars) - 64, 2)
    return {
        "format": "fastq",
        "read_count": len(lengths),
        "min_length": min(lengths),
        "max_length": max(lengths),
        "median_length": int(statistics.median(lengths)),
        "mean_length": round(statistics.fmean(lengths), 2),
        "mean_quality": mean_qual,
        "phred_encoding": encoding,
        "adapter_hits_first_100k": adapter_hits,
        "sampled_for_adapters": sampled,
    }


def summarize_vcf(path: str) -> dict[str, Any]:
    import cyvcf2
    vcf = cyvcf2.VCF(path)
    samples = list(vcf.samples)
    counts = {"snv": 0, "indel": 0, "mnp": 0, "sv": 0, "other": 0}
    pass_count = 0
    filtered_count = 0
    per_chrom: Counter = Counter()
    transitions = 0
    transversions = 0
    transition_set = {frozenset({"A", "G"}), frozenset({"C", "T"})}
    total = 0
    for v in vcf:
        total += 1
        per_chrom[v.CHROM] += 1
        if v.FILTER is None or v.FILTER == "PASS":
            pass_count += 1
        else:
            filtered_count += 1
        ref = v.REF or ""
        alts = v.ALT or []
        if not alts:
            counts["other"] += 1
            continue
        # Classify by the first alt
        alt = alts[0]
        if v.INFO.get("SVTYPE"):
            counts["sv"] += 1
        elif len(ref) == 1 and len(alt) == 1 and ref.isalpha() and alt.isalpha():
            counts["snv"] += 1
            pair = frozenset({ref.upper(), alt.upper()})
            if pair in transition_set:
                transitions += 1
            elif len(pair) == 2:
                transversions += 1
        elif len(ref) == len(alt) and len(ref) > 1:
            counts["mnp"] += 1
        else:
            counts["indel"] += 1
    tstv = round(transitions / transversions, 3) if transversions else None
    return {
        "format": "vcf",
        "variant_count": total,
        "snv": counts["snv"],
        "indel": counts["indel"],
        "mnp": counts["mnp"],
        "sv": counts["sv"],
        "ts_tv_ratio": tstv,
        "pass_count": pass_count,
        "filtered_count": filtered_count,
        "per_chromosome": dict(per_chrom),
        "samples": samples,
    }


def summarize_alignments(path: str, fmt: str) -> dict[str, Any]:
    import pysam
    mode = {"bam": "rb", "sam": "r", "cram": "rc"}[fmt]
    af = pysam.AlignmentFile(path, mode)
    mapped = 0
    unmapped = 0
    dups = 0
    total = 0
    for read in af.fetch(until_eof=True):
        total += 1
        if read.is_unmapped:
            unmapped += 1
        else:
            mapped += 1
        if read.is_duplicate:
            dups += 1
    contigs = list(af.references) if af.references else []
    out = {
        "format": fmt,
        "read_count": total,
        "mapped": mapped,
        "unmapped": unmapped,
        "duplicate_rate": round(dups / total, 5) if total else 0.0,
        "contigs": contigs,
    }
    # Try a cheap mean-coverage if index present
    try:
        idx_stats = af.get_index_statistics() if af.has_index() else None
        if idx_stats:
            out["mean_coverage_proxy"] = round(
                sum(s.mapped for s in idx_stats) / max(1, len(contigs)), 3
            )
    except (ValueError, AttributeError):
        pass
    af.close()
    return out


def summarize_intervals(path: str, fmt: str) -> dict[str, Any]:
    feature_types: Counter = Counter()
    chrom_span: dict[str, int] = {}
    sources: set[str] = set()
    with open_maybe_gzip(path, "rt") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#") or line.startswith("track"):
                continue
            parts = line.split("\t")
            if fmt == "bed":
                if len(parts) < 3:
                    continue
                chrom, start, end = parts[0], int(parts[1]), int(parts[2])
                feature_types["region"] += 1
                chrom_span[chrom] = chrom_span.get(chrom, 0) + (end - start)
            else:  # gff / gtf
                if len(parts) < 9:
                    continue
                chrom = parts[0]
                source = parts[1]
                ftype = parts[2]
                start = int(parts[3])
                end = int(parts[4])
                feature_types[ftype] += 1
                chrom_span[chrom] = chrom_span.get(chrom, 0) + (end - start + 1)
                sources.add(source)
    return {
        "format": fmt,
        "feature_count": sum(feature_types.values()),
        "feature_types": dict(feature_types),
        "span_per_chromosome": chrom_span,
        "sources": sorted(sources) if sources else [],
    }


_NO_CALL_TOKENS = {"", "-", "--", "0", "00", "0 0"}


def summarize_consumer_dna(path: str, kind: str) -> dict[str, Any]:
    chroms: Counter = Counter()
    total = 0
    no_call = 0
    for rsid, chrom, pos, genotype in iter_consumer_dna(path):
        total += 1
        chroms[chrom] += 1
        if genotype.strip() in _NO_CALL_TOKENS:
            no_call += 1
    return {
        "format": f"consumer_dna:{kind}",
        "snp_count": total,
        "chromosome_distribution": dict(chroms),
        "build": detect_consumer_dna_build(path),
        "no_call_rate": round(no_call / total, 5) if total else 0.0,
    }


def render_text(d: dict[str, Any]) -> str:
    lines = [f"{d['format']}"]
    for k, v in d.items():
        if k == "format":
            continue
        if isinstance(v, dict):
            lines.append(f"  {k}:")
            for kk, vv in v.items():
                lines.append(f"    {kk}: {vv}")
        elif isinstance(v, list) and len(v) > 10:
            lines.append(f"  {k}: ({len(v)} items, first 5: {v[:5]})")
        else:
            lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    as_json = False
    args = argv[1:]
    if "--json" in args:
        as_json = True
        args.remove("--json")
    if len(args) != 1 or args[0] in {"-h", "--help"}:
        print("usage: summarize.py <path> [--json]", file=sys.stderr)
        return 2
    path = args[0]
    try:
        info: FormatInfo = detect_format(path)
    except FileNotFoundError:
        die(f"no such file: {path}")
    fmt = info.format
    if fmt == "fasta":
        result = summarize_fasta(path)
    elif fmt == "fastq":
        result = summarize_fastq(path)
    elif fmt == "vcf":
        result = summarize_vcf(path)
    elif fmt in {"bam", "sam", "cram"}:
        result = summarize_alignments(path, fmt)
    elif fmt in {"bed", "gff", "gtf"}:
        result = summarize_intervals(path, fmt)
    elif fmt.startswith("consumer_dna:"):
        result = summarize_consumer_dna(path, fmt.split(":", 1)[1])
    else:
        die(f"unsupported or unknown format: {fmt}")
    if as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(render_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
