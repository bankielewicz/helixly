#!/usr/bin/env python3
"""verify.py — Phase 7 final verification (deterministic, no network).

Runs the SPEC ``## Verification Commands`` (1–7) over a finished canonical
report and emits a pass/fail report. It is a *gate*, not an author: it reads the
canonical output documents, the genotype-truth INDEX, the source genome, the
archive, and the continuation prompts, and reports whether the SPEC's invariants
hold. It writes nothing and makes no network call.

Checks (SPEC ``## Verification Commands`` 1–7):

  1. **archive_integrity** — count of files under the archive directory; when
     ``--expected-archive-count`` is given it must match (the Phase-0 manifest).
  2. **genome_sha** — the live source-genome SHA-256 matches the
     ``source_genome_sha256`` declared in every canonical doc's provenance block
     (drift detection — a mismatch is a STOP per the SPEC).
  3. **provenance_coverage** — every canonical doc carries ``## Provenance
     Summary`` (SPEC Rule 6).
  4. **aspirational_narrow** — the SPEC's narrow phrase list ("may benefit",
     "might consider", …) appears in no canonical doc.
  4b. **aspirational_blacklist** — the full aspirational-phrase blacklist sweep,
     reusing ``_common.find_blacklist_hits`` so it is *identical* to the write
     gate (same patterns, same exemptions: fenced code, inline code, Glossary /
     Appendix, archive-attributed verbatim quotes, stable ClinVar terminology).
  5. **rsid_traceability** — every rsID cited in a canonical doc is present in the
     INDEX. *Traceability semantics (locked decision):* a cited rsID **absent
     from the INDEX** is the failure (invented / never looked up); a cited rsID
     that is in the INDEX with ``found = n`` is **allowed** — those are the
     chip-coverage gaps the SPEC's Phase 4/5 deliverables mandate recording — and
     is reported as a soft note, not a failure.
  6. **genotype_consistency** — every rendered genotype triple
     ``rsid chr:pos genotype`` in a canonical doc agrees with the INDEX genotype
     for that rsID (SPEC Rule 4: docs copy the genotype from the INDEX, never
     re-derive it). Because every citation is checked against the single INDEX
     truth, cross-doc agreement follows for free.
  7. **continuation_prompts** — ``phase0_prompt.md`` … ``phase7_prompt.md`` all
     exist in the prompts directory.

**Scope of the aspirational sweep (DECISION, documented).** Checks 4 and 4b scan
only the canonical output documents — ``<out>/*.md`` at the top level. This
deliberately **excludes** ``assets/templates/*.html`` (design mockups carry hedge
words in baked sample content) and the immutable ``<out>/archive/`` subtree (v1
docs), neither of which is a top-level canonical ``.md``.

Determinism: the report carries no wall-clock date and every list is sorted, so
the same inputs produce a byte-identical report.

CLI::

    verify.py --out <output_dir> [--index <INDEX.tsv>] [--genome <source_genome>]
              [--archive <archive_dir>] [--prompts <prompts_dir>]
              [--expected-archive-count N] [--json]

Checks whose inputs are not supplied are reported as ``skip`` (loudly — a skipped
check is a coverage gap, never a silent pass). Exit code is ``0`` when no check
failed, ``1`` otherwise.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import _common
from _common import (
    extract_rsids,
    find_blacklist_hits,
    parse_flat_args,
    sha256_file,
)

# Canonical-doc exclusion (SPEC Verification Command 3): these are report
# artifacts, not provenance-bearing analysis documents.
_EXCLUDE_PREFIXES = ("SPEC_", "INDEX_", "REPORT_")
_EXCLUDE_NAMES = ("CHANGELOG.md",)

# SPEC Verification Command 4 (narrow check).
_NARROW_PATTERN = re.compile(
    r"may benefit|might consider|could be helpful|future possibility|"
    r"patients with this variant often",
    re.IGNORECASE,
)

# The rendered genotype triple in the markdown twin: `rsid chr:pos genotype`,
# e.g. `rs1801133 1:11,856,378 AG`. Anchored to backticks + the chr:pos shape so
# prose like "rs1801133 in CBS" cannot masquerade as a genotype citation.
_TRIPLE_RE = re.compile(r"`(rs\d+)\s+[0-9XYMT]+:[\d,]+\s+(--|[ACGTDI]{1,2})`")

EXPECTED_PROMPTS = tuple(f"phase{n}_prompt.md" for n in range(8))


@dataclass
class CheckResult:
    name: str
    status: str  # "pass" | "fail" | "skip"
    summary: str
    items: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "summary": self.summary,
                "items": self.items}


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def canonical_docs(out_dir: Path) -> list[Path]:
    """Top-level ``*.md`` canonical analysis docs, sorted, report artifacts excluded.

    Top-level only: the ``archive/`` subtree and the skill's template assets are
    never scanned (see module docstring — the aspirational-sweep scope decision).
    """
    docs = []
    for p in sorted(out_dir.glob("*.md")):
        if p.name in _EXCLUDE_NAMES or p.name.startswith(_EXCLUDE_PREFIXES):
            continue
        docs.append(p)
    return docs


def _non_archive_quote_text(text: str) -> str:
    """Drop archive-attributed verbatim-quote lines so their (intentionally
    aspirational, possibly out-of-INDEX) content is not mistaken for a live claim.

    Reuses the same exemption the write gate uses (``_archive_quote_line_flags``)
    plus single-line ``[verbatim from archive…]`` bullets (the Provenance
    Summary's "Removed claims" lines).
    """
    lines = text.splitlines()
    flags = _common._archive_quote_line_flags(lines)
    kept = [
        ln
        for i, ln in enumerate(lines)
        if not flags[i] and "[verbatim from archive" not in ln
    ]
    return "\n".join(kept)


def _frontmatter(text: str) -> dict[str, str]:
    """Parse the leading ``---`` YAML block as flat ``key: value`` pairs."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: dict[str, str] = {}
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        if ":" in ln:
            k, _, v = ln.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def load_index(index_path: Path) -> dict[str, tuple[str, str]]:
    """INDEX TSV → ``{rsid: (genotype, found)}`` keyed by header name."""
    lines = index_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise _common.DecoderError(f"empty INDEX: {index_path}")
    header = lines[0].split("\t")
    try:
        i_rsid = header.index("rsid")
        i_gt = header.index("genotype")
        i_found = header.index("found")
    except ValueError as e:
        raise _common.DecoderError(f"INDEX missing required column: {e}") from e
    out: dict[str, tuple[str, str]] = {}
    for ln in lines[1:]:
        if not ln.strip():
            continue
        cols = ln.split("\t")
        if len(cols) <= max(i_rsid, i_gt, i_found):
            continue
        out[cols[i_rsid]] = (cols[i_gt], cols[i_found])
    return out


# --------------------------------------------------------------------------- #
# Individual checks
# --------------------------------------------------------------------------- #


def check_archive_integrity(archive_dir: Path | None, expected: int | None) -> CheckResult:
    name = "archive_integrity"
    if archive_dir is None:
        return CheckResult(name, "skip", "no --archive given")
    if not archive_dir.is_dir():
        return CheckResult(name, "fail", f"archive directory not found: {archive_dir}")
    count = sum(1 for p in archive_dir.rglob("*") if p.is_file())
    if expected is None:
        return CheckResult(name, "pass", f"{count} archived file(s) (no expected count given)")
    if count == expected:
        return CheckResult(name, "pass", f"{count} archived file(s) match expected count")
    return CheckResult(name, "fail", f"archive has {count} file(s), expected {expected}")


def check_genome_sha(genome: Path | None, docs: list[Path]) -> CheckResult:
    name = "genome_sha"
    if genome is None:
        return CheckResult(name, "skip", "no --genome given")
    if not genome.is_file():
        return CheckResult(name, "fail", f"source genome not found: {genome}")
    live = sha256_file(genome)
    mismatches: list[str] = []
    no_field: list[str] = []
    declaring = 0
    for d in docs:
        declared = _frontmatter(d.read_text(encoding="utf-8")).get("source_genome_sha256")
        if not declared:
            no_field.append(d.name)
            continue
        declaring += 1
        # SHA-256 hex is case-insensitive: a provenance block written by PowerShell
        # Get-FileHash is uppercase, sha256_file is lowercase. Compare case-folded
        # so identical hashes are not mis-reported as drift.
        if declared.lower() != live.lower():
            mismatches.append(f"{d.name}: declares {declared}, live {live}")
    items = sorted(mismatches) + sorted(f"{n}: no source_genome_sha256 in provenance" for n in no_field)
    if mismatches:
        return CheckResult(name, "fail", f"genome SHA drift in {len(mismatches)} doc(s)", items)
    return CheckResult(name, "pass", f"live SHA matches all {declaring} declaring doc(s)", items)


def check_provenance_coverage(docs: list[Path]) -> CheckResult:
    name = "provenance_coverage"
    missing = sorted(d.name for d in docs if "## Provenance Summary" not in d.read_text(encoding="utf-8"))
    if missing:
        return CheckResult(name, "fail", f"{len(missing)} doc(s) lack '## Provenance Summary'", missing)
    return CheckResult(name, "pass", f"all {len(docs)} canonical doc(s) carry a Provenance Summary")


def _narrow_hits(text: str) -> list[int]:
    """Narrow-phrase line numbers, exempting fenced code + archive-attributed quotes."""
    lines = text.splitlines()
    code_flags = _common._fenced_code_line_flags(lines)
    quote_flags = _common._archive_quote_line_flags(lines)
    hits: list[int] = []
    for i, ln in enumerate(lines):
        if code_flags[i] or quote_flags[i] or "[verbatim from archive" in ln:
            continue
        if _NARROW_PATTERN.search(ln):
            hits.append(i + 1)
    return hits


def check_aspirational_narrow(docs: list[Path]) -> CheckResult:
    name = "aspirational_narrow"
    offenders: list[str] = []
    for d in docs:
        hits = _narrow_hits(d.read_text(encoding="utf-8"))
        offenders.extend(f"{d.name}:{ln}" for ln in hits)
    offenders.sort()
    if offenders:
        return CheckResult(name, "fail", f"{len(offenders)} narrow-phrase hit(s)", offenders)
    return CheckResult(name, "pass", f"no narrow aspirational phrases in {len(docs)} doc(s)")


def check_aspirational_blacklist(docs: list[Path]) -> CheckResult:
    name = "aspirational_blacklist"
    offenders: list[str] = []
    for d in docs:
        for h in find_blacklist_hits(d.read_text(encoding="utf-8")):
            offenders.append(f"{d.name}:{h.lineno}: {h.token}")
    offenders.sort()
    if offenders:
        return CheckResult(name, "fail", f"{len(offenders)} non-exempt blacklist hit(s)", offenders)
    return CheckResult(name, "pass", f"no non-exempt aspirational tokens in {len(docs)} doc(s)")


def check_rsid_traceability(index: dict | None, docs: list[Path]) -> CheckResult:
    name = "rsid_traceability"
    if index is None:
        return CheckResult(name, "skip", "no --index given")
    untraceable: set[str] = set()
    gap_notes: set[str] = set()
    for d in docs:
        live_text = _non_archive_quote_text(d.read_text(encoding="utf-8"))
        for rsid in extract_rsids(live_text):
            entry = index.get(rsid)
            if entry is None:
                untraceable.add(f"{d.name}: {rsid} not in INDEX")
            elif entry[1] != "y":
                gap_notes.add(f"{d.name}: {rsid} in INDEX with found=n (chip-coverage gap)")
    items = sorted(untraceable) + sorted(gap_notes)
    if untraceable:
        return CheckResult(name, "fail", f"{len(untraceable)} cited rsID(s) absent from INDEX", items)
    summary = "all cited rsIDs are traceable to the INDEX"
    if gap_notes:
        summary += f" ({len(gap_notes)} found=n chip-gap citation(s) noted)"
    return CheckResult(name, "pass", summary, items)


def check_genotype_consistency(index: dict | None, docs: list[Path]) -> CheckResult:
    name = "genotype_consistency"
    if index is None:
        return CheckResult(name, "skip", "no --index given")
    checked = 0
    mismatches: list[str] = []
    for d in docs:
        for rsid, gt in _TRIPLE_RE.findall(d.read_text(encoding="utf-8")):
            entry = index.get(rsid)
            if entry is None:
                continue  # traceability is check 5's job
            checked += 1
            if gt != entry[0]:
                mismatches.append(f"{d.name}: {rsid} cites {gt}, INDEX has {entry[0]}")
    mismatches.sort()
    if mismatches:
        return CheckResult(name, "fail", f"{len(mismatches)} genotype mismatch(es) vs INDEX", mismatches)
    return CheckResult(name, "pass", f"{checked} genotype citation(s) agree with the INDEX")


def check_continuation_prompts(prompts_dir: Path | None) -> CheckResult:
    name = "continuation_prompts"
    if prompts_dir is None:
        return CheckResult(name, "skip", "no --prompts given")
    if not prompts_dir.is_dir():
        return CheckResult(name, "fail", f"prompts directory not found: {prompts_dir}")
    missing = sorted(p for p in EXPECTED_PROMPTS if not (prompts_dir / p).is_file())
    if missing:
        return CheckResult(name, "fail", f"{len(missing)} continuation prompt(s) missing", missing)
    return CheckResult(name, "pass", "phase0_prompt.md … phase7_prompt.md all present")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def run_verify(
    out_dir,
    *,
    index_path=None,
    genome_path=None,
    archive_dir=None,
    prompts_dir=None,
    expected_archive_count=None,
) -> list[CheckResult]:
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        raise _common.DecoderError(f"output directory not found: {out_dir}")
    docs = canonical_docs(out_dir)
    index = load_index(Path(index_path)) if index_path else None
    return [
        check_archive_integrity(Path(archive_dir) if archive_dir else None, expected_archive_count),
        check_genome_sha(Path(genome_path) if genome_path else None, docs),
        check_provenance_coverage(docs),
        check_aspirational_narrow(docs),
        check_aspirational_blacklist(docs),
        check_rsid_traceability(index, docs),
        check_genotype_consistency(index, docs),
        check_continuation_prompts(Path(prompts_dir) if prompts_dir else None),
    ]


def render_report(results: list[CheckResult]) -> str:
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    skipped = sum(1 for r in results if r.status == "skip")
    lines = [
        f"genome-decoder verify — {len(results)} checks: "
        f"{passed} passed, {failed} failed, {skipped} skipped"
    ]
    for r in results:
        lines.append(f"[{r.status.upper()}] {r.name} — {r.summary}")
        for item in r.items:
            lines.append(f"    - {item}")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    positionals, flags = parse_flat_args(
        argv[1:],
        {"--out", "--index", "--genome", "--archive", "--prompts", "--expected-archive-count"},
        bool_flags={"--json"},
    )
    out_dir = flags.get("--out") or (positionals[0] if positionals else None)
    if not out_dir:
        _common.die("usage: verify.py --out <output_dir> [--index <INDEX.tsv>] "
                    "[--genome <genome>] [--archive <dir>] [--prompts <dir>] "
                    "[--expected-archive-count N] [--json]")
    expected = flags.get("--expected-archive-count")
    if expected is not None:
        try:
            expected = int(expected)
        except ValueError:
            _common.die("--expected-archive-count must be an integer")
    try:
        results = run_verify(
            out_dir,
            index_path=flags.get("--index"),
            genome_path=flags.get("--genome"),
            archive_dir=flags.get("--archive"),
            prompts_dir=flags.get("--prompts"),
            expected_archive_count=expected,
        )
    except _common.DecoderError as e:
        _common.die(str(e))
    if "--json" in flags:
        print(json.dumps([r.as_dict() for r in results], indent=2, sort_keys=True))
    else:
        sys.stdout.write(render_report(results))
    return 1 if any(r.status == "fail" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
