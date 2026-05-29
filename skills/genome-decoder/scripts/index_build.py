#!/usr/bin/env python3
"""index_build.py — Phase 0 genotype-truth INDEX builder (deterministic).

SPEC Phase 0 deliverables 5 & 6. Builds ``INDEX_genotype_truth.tsv`` (the
machine-readable genotype-truth table) plus its ``INDEX_genotype_truth.md``
human companion from two inputs:

  1. a consumer DNA export (23andMe / AncestryDNA / MyHeritage), and
  2. an archive directory of prior analysis documents to be re-audited.

The build is purely mechanical and reproducible — it authors no clinical prose
and makes **no network calls**:

  (a) ``identify.py``  — assert the source is a ``consumer_dna:*`` export.
  (b) ``summarize.py --json`` — record ``snp_count`` / ``build`` / ``no_call_rate``.
      A ``build`` of ``null`` is a STOP (the reference assembly is never
      defaulted); the tool raises and the agent surfaces the question.
  (c) ``sha256_file`` of the source genome — recorded for later drift detection.
  (d) the rsID *pool* = every ``rs\\d+`` token across the archive ``*.md`` docs.
  (e) ``lookup.py --columns rsid,chrom,pos,genotype`` — the per-rsID base rows.
  (f) the INDEX TSV — the substrate rows joined with the audit-specific columns
      ``found`` (via :func:`_common.genotype_found`), ``source_docs`` (the sorted
      archive basenames citing each rsID), and ``discovered_in_phase`` (``0`` for
      every Phase-0 row; Phase 6 stamps ``6``).
  (g) the ``.md`` companion (coverage counts + a chip-coverage-gap table).
  (h) the INDEX SHA-256 — emitted to stdout, never written into the file it hashes.

Determinism is scoped to the tool's outputs: the same source genome + archive
produce byte-identical ``.tsv`` and ``.md``. There is no wall-clock date in
either file — the pool order is fixed (archive docs sorted, rsIDs in first-seen
order) and ``source_docs`` is sorted, so two runs diff to nothing.

CLI::

    index_build.py <source_genome> --archive <dir> --out <dir> [--snapshot-date YYYY-MM-DD]

(``--snapshot-date`` is accepted for interface parity with the network-using
phase tools; index_build does no network and emits no date.)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import _common
from _common import (
    LOOKUP_COLUMNS,
    NOT_TESTED,
    DecoderError,
    SubstrateError,
    die,
    extract_rsids,
    genotype_found,
    iter_archive_docs,
    parse_flat_args,
    sha256_file,
)

# The SPEC Phase 0 INDEX schema, extended with the audit-specific columns
# genome-decoder adds on top of the substrate's 4-column lookup output.
INDEX_COLUMNS = (
    "rsid",
    "chromosome",
    "position",
    "genotype",
    "found",
    "source_docs",
    "discovered_in_phase",
)
DISCOVERED_IN_PHASE_0 = "0"

INDEX_TSV = "INDEX_genotype_truth.tsv"
INDEX_MD = "INDEX_genotype_truth.md"
POOL_FILENAME = "INDEX_rsid_pool.txt"


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #


def _genome_fingerprint(source_genome: Path) -> dict:
    """Steps (a)+(b): identify + summarize the source genome.

    Asserts the export is a consumer DNA file and that ``summarize.py`` resolved
    a reference assembly. ``build=null`` is a STOP condition (SPEC: assembly is
    declared by the file's header, never defaulted) — the tool raises rather than
    guessing, and the agent decides what to do next.
    """
    ident = _common.run_substrate("identify.py", str(source_genome), json_out=True)
    fmt = ident.get("format", "")
    if not fmt.startswith("consumer_dna:"):
        raise SubstrateError(
            f"source genome format {fmt!r} is not a consumer_dna:* export; "
            "index_build builds the genotype-truth INDEX from a 23andMe / "
            "AncestryDNA / MyHeritage raw file only."
        )
    summ = _common.run_substrate("summarize.py", str(source_genome), "--json", json_out=True)
    build = summ.get("build")
    if build is None:
        raise SubstrateError(
            "summarize.py returned build=null — the reference assembly could not "
            "be detected from the genome header. STOP: the assembly is never "
            "defaulted (SPEC). Confirm the assembly and re-run."
        )
    return {
        "format": fmt,
        "build": build,
        "snp_count": summ.get("snp_count"),
        "no_call_rate": summ.get("no_call_rate"),
    }


def _collect_pool(archive_dir: Path) -> tuple[list[str], dict[str, list[str]]]:
    """Step (d): the rsID pool + the archive docs that cite each rsID.

    Pool order is deterministic: archive docs are visited in sorted order
    (``iter_archive_docs``) and rsIDs within a doc in first-seen order, so the
    pool — and therefore every downstream row order — is stable across runs.
    ``source_docs`` is recorded as *sorted basenames*, not absolute paths: it is
    both meaningful (the archive dir is implied) and privacy-safe (a real run's
    ``private/`` path never leaks into the INDEX).
    """
    pool_order: list[str] = []
    seen: set[str] = set()
    rsid_to_docs: dict[str, set[str]] = {}
    for doc in iter_archive_docs(archive_dir):
        text = doc.read_text(encoding="utf-8", errors="replace")
        for rsid in extract_rsids(text):
            if rsid not in seen:
                seen.add(rsid)
                pool_order.append(rsid)
            rsid_to_docs.setdefault(rsid, set()).add(doc.name)
    return pool_order, {r: sorted(docs) for r, docs in rsid_to_docs.items()}


def _parse_lookup_tsv(tsv: str) -> dict[str, tuple[str, str, str]]:
    """Parse ``lookup.py --columns`` TSV into ``{rsid: (chrom, pos, genotype)}``.

    The header is validated against the contracted columns and a mismatch raises
    ``SubstrateError`` — no silent fallback, matching the foundation's stance
    that a wrong-but-plausible value is worse than a stop.
    """
    lines = tsv.splitlines()
    if not lines:
        raise SubstrateError("lookup.py returned no output")
    expected = LOOKUP_COLUMNS.split(",")
    header = lines[0].split("\t")
    if header != expected:
        raise SubstrateError(
            f"lookup.py header {header} does not match expected {expected}; "
            "the substrate is missing the --columns capability (PR #23 or later)."
        )
    rows: dict[str, tuple[str, str, str]] = {}
    for ln in lines[1:]:
        if not ln.strip():
            continue
        parts = ln.split("\t")
        if len(parts) != 4:
            raise SubstrateError(f"malformed lookup.py row: {ln!r}")
        rsid, chrom, pos, genotype = parts
        rows[rsid] = (chrom, pos, genotype)
    return rows


def _lookup_rows(source_genome: Path, pool: list[str], out_dir: Path) -> dict[str, tuple[str, str, str]]:
    """Step (e): ``lookup.py`` for the whole pool, joined by rsID.

    The pool is written to a file (one rsID per line) so an arbitrarily large
    archive cannot overflow the command line; ``lookup.py`` accepts a file path
    or a CSV. An empty pool skips the substrate call entirely.
    """
    if not pool:
        return {}
    pool_path = out_dir / POOL_FILENAME
    pool_path.write_text("\n".join(pool) + "\n", encoding="utf-8", newline="\n")
    tsv = _common.run_substrate(
        "lookup.py", str(source_genome), "--rsids", str(pool_path), "--columns", LOOKUP_COLUMNS
    )
    return _parse_lookup_tsv(tsv)


def _render_companion(
    source_genome: Path,
    source_sha256: str,
    fp: dict,
    pool: list[str],
    found_count: int,
    gaps: list[tuple[str, str, list[str]]],
) -> str:
    """Step (g): the dateless human companion (coverage + gap table).

    Carries no wall-clock date so it is byte-deterministic. ``gaps`` is already
    in pool order, so the table is stable.
    """
    total = len(pool)
    not_found = total - found_count
    lines: list[str] = [
        "# INDEX_genotype_truth — genotype-truth table",
        "",
        "Deterministic Phase 0 extract: every rsID cited in the archived analysis",
        "documents, looked up against the source consumer-DNA export. Built by",
        "`index_build.py` — no network, no clinical interpretation.",
        "",
        "## Source",
        "",
        f"- file: `{source_genome.name}`",
        f"- sha256: `{source_sha256}`",
        f"- assembly: `{fp['build']}`",
        f"- data rows (snp_count): {fp['snp_count']}",
        f"- no-call rate: {fp['no_call_rate']}",
        "",
        "## Coverage",
        "",
        f"- rsIDs cited in archive: {total}",
        f"- found on chip (found = y): {found_count}",
        f"- not found (found = n): {not_found}",
        "",
        "## Chip coverage gaps (found = n)",
        "",
    ]
    if gaps:
        lines.append("| rsid | genotype | source_docs |")
        lines.append("| --- | --- | --- |")
        for rsid, genotype, docs in gaps:
            lines.append(f"| {rsid} | {genotype} | {','.join(docs)} |")
    else:
        lines.append("_None — every cited rsID was called on the chip._")
    lines.append("")
    return "\n".join(lines) + "\n"


def build_index(source_genome, archive_dir, out_dir) -> dict:
    """Build the INDEX TSV + companion. Returns a deterministic summary dict.

    Raises ``DecoderError`` subclasses on any STOP condition (non-consumer
    format, ``build=null``, substrate contract violation). Writes nothing on a
    failed fingerprint.
    """
    source_genome = Path(source_genome)
    archive_dir = Path(archive_dir)
    out_dir = Path(out_dir)
    if not source_genome.exists():
        die(f"source genome not found: {source_genome}")
    if not archive_dir.is_dir():
        die(f"archive directory not found: {archive_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    fp = _genome_fingerprint(source_genome)
    source_sha256 = sha256_file(source_genome)
    pool, rsid_to_docs = _collect_pool(archive_dir)
    lookup = _lookup_rows(source_genome, pool, out_dir)

    tsv_lines = ["\t".join(INDEX_COLUMNS)]
    found_count = 0
    gaps: list[tuple[str, str, list[str]]] = []
    for rsid in pool:
        chrom, pos, genotype = lookup.get(rsid, ("", "", NOT_TESTED))
        docs = rsid_to_docs.get(rsid, [])
        is_found = genotype_found(genotype)
        if is_found:
            found_count += 1
        else:
            gaps.append((rsid, genotype, docs))
        tsv_lines.append(
            "\t".join(
                [
                    rsid,
                    chrom,
                    pos,
                    genotype,
                    "y" if is_found else "n",
                    ",".join(docs),
                    DISCOVERED_IN_PHASE_0,
                ]
            )
        )
    tsv_text = "\n".join(tsv_lines) + "\n"
    tsv_path = out_dir / INDEX_TSV
    tsv_path.write_text(tsv_text, encoding="utf-8", newline="\n")
    index_sha256 = sha256_file(tsv_path)

    md_path = out_dir / INDEX_MD
    md_path.write_text(
        _render_companion(source_genome, source_sha256, fp, pool, found_count, gaps),
        encoding="utf-8",
        newline="\n",
    )

    return {
        "index_path": str(tsv_path),
        "index_sha256": index_sha256,
        "companion_path": str(md_path),
        "source_sha256": source_sha256,
        "assembly": fp["build"],
        "snp_count": fp["snp_count"],
        "no_call_rate": fp["no_call_rate"],
        "rsids_total": len(pool),
        "rsids_found": found_count,
        "rsids_not_found": len(pool) - found_count,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str]) -> int:
    positionals, flags = parse_flat_args(
        argv[1:], {"--archive", "--out", "--snapshot-date"}
    )
    if not positionals:
        die(
            "usage: index_build.py <source_genome> --archive <dir> --out <dir> "
            "[--snapshot-date YYYY-MM-DD]"
        )
    if "--archive" not in flags or "--out" not in flags:
        die("index_build.py requires --archive <dir> and --out <dir>")
    try:
        summary = build_index(positionals[0], flags["--archive"], flags["--out"])
    except DecoderError as e:
        die(str(e))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
