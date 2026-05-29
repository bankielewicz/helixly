#!/usr/bin/env python3
"""audit.py — Phase 1 provenance & aspirational-claim audit (read-only).

The *mechanical half* of SPEC Phase 1. It reads the archived v1 documents and
the Phase-0 INDEX and emits structured findings plus a rule-based **provisional**
disposition (``delete`` / ``rewrite-with-citation`` / ``keep``) per claim. It
writes no clinical prose, makes no network call, runs no substrate, and never
touches the archive. The agent reviews every disposition, overrides any with a
documented reason, and authors ``REPORT_phase1_audit.md`` — audit.py is not the
final word.

Per the SPEC Phase 1 deliverable, the eight subsections computed per claim are:

  1. missing rsID linkage          5. internal v1↔v1 contradiction
  2. missing allow-list citation   6. rebuild recommendation (the disposition)
  3. aspirational phrasing         7. project-specific propagation
  4. rsID cited but absent          8. v1 genotype vs INDEX
     from INDEX

Locked decisions (recorded so the audit is reproducible and unambiguous):

* **Claim unit = one markdown line.** No sentence splitting — line granularity is
  deterministic and maps one-to-one to ``find_blacklist_hits``'s line numbers. A
  line is captured as a claim when it carries an rsID, a gene-lexicon token, a
  clinical-lexicon noun, or a non-exempt blacklist hit. Intentionally
  over-inclusive; the agent prunes.
* **Supporting rsID = present in INDEX with ``found == "y"``** (an actually-called
  genotype, per SPEC Rule 1a's "observed genotype"). A claim resting only on a
  ``found == "n"`` (untested) rsID has no support and is deleted/rewritten.
* **Subsection 7** is driven by an optional ``--project-terms`` list; without it,
  subsection 7 emits nothing and the agent identifies the corrections itself.
* **Subsections 5 and 8 are advisory** heuristic flags; they never change the
  disposition, which follows only the locked 3-clause rule below.

CLI::

    audit.py --archive <dir> --index <INDEX_genotype_truth.tsv> --out <dir>
             [--project-terms <file|csv>] [--snapshot-date YYYY-MM-DD]

Outputs (to ``--out``, byte-deterministic, dateless):
  * ``audit_findings.json`` — full structured findings + counts + INDEX SHA-256.
  * ``audit_claims.tsv``     — flat per-claim disposition table.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import _common
from _common import (
    die,
    extract_rsids,
    find_blacklist_hits,
    iter_archive_docs,
    load_allowlist,
    parse_flat_args,
    sha256_file,
)

# --------------------------------------------------------------------------- #
# Locked lexicons (auditable + editable in one place)
# --------------------------------------------------------------------------- #

# Union of the SPEC's fixed Phase 3 / 4 / 5 gene checklists.
GENE_LEXICON = (
    "CYP2D6", "CYP2C19", "CYP2C9", "CYP1A2", "CYP3A4", "CYP3A5", "VKORC1", "TPMT",
    "NUDT15", "NAT2", "UGT1A1", "SLCO1B1", "DPYD",  # Phase 3 pharmacogenes
    "MTHFR", "MTR", "MTRR", "CBS", "BHMT", "AHCY", "SHMT1", "MAT1A", "TYMS",  # Phase 4
    "ABCB11", "NR1H4", "ABCB4", "GC", "NPC1L1", "APOA5",  # Phase 5
)
_GENE_RE = re.compile(r"\b(" + "|".join(GENE_LEXICON) + r")\b")

# Clinical / health / dietary nouns. Whole-word, case-insensitive.
CLINICAL_LEXICON = (
    "risk", "metabolizer", "metabolism", "deficiency", "sensitivity", "dose",
    "dosing", "dosage", "supplement", "allele", "carrier", "variant", "genotype",
    "pathogenic", "enzyme",
)
_CLINICAL_RE = re.compile(r"\b(" + "|".join(CLINICAL_LEXICON) + r")\b", re.IGNORECASE)

# Allow-list citation markers (SPEC "Evidence Sources" identifier formats). A bare
# rsID is deliberately NOT here: per the SPEC, dbSNP/rsID backs metadata only and
# cannot back a clinical claim on its own. url_root markers are added at runtime
# from allowlist_sources.json.
_CITATION_MARKERS = (
    r"PMID", r"VCV\d+", r"RCV\d+", r"ClinVar", r"CPIC", r"PharmGKB", r"FDA",
    r"GCST\d+", r"GWAS Catalog", r"gnomAD",
)

# A standalone genotype-shaped token (conservative — see subsection 5/8).
_GENOTYPE_RE = re.compile(r"(?<![A-Za-z0-9])([ACGT]{2}|[ACGT][/|][ACGT]|[DI]{2}|--)(?![A-Za-z0-9])")

DISPOSITIONS = ("delete", "rewrite-with-citation", "keep")

FINDINGS_JSON = "audit_findings.json"
CLAIMS_TSV = "audit_claims.tsv"


# --------------------------------------------------------------------------- #
# INDEX
# --------------------------------------------------------------------------- #


def load_index(index_path: Path) -> dict[str, tuple[str, str]]:
    """INDEX TSV → ``{rsid: (genotype, found)}`` keyed by header name."""
    lines = index_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise _common.DecoderError(f"empty INDEX: {index_path}")
    header = lines[0].split("\t")
    try:
        i_rsid, i_gt, i_found = header.index("rsid"), header.index("genotype"), header.index("found")
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
# Helpers
# --------------------------------------------------------------------------- #


def _citation_regex() -> re.Pattern:
    roots = [re.escape(s.get("url_root", "")) for s in load_allowlist().values()
             if isinstance(s, dict) and s.get("url_root")]
    alts = list(_CITATION_MARKERS) + roots
    return re.compile("|".join(a for a in alts if a), re.IGNORECASE)


def _norm_genotype(g: str) -> str:
    """Normalize an allele pair for comparison: ``A/G``→``AG``, ``GA``→``AG``."""
    g = g.replace("/", "").replace("|", "").strip()
    if len(g) == 2 and set(g) <= set("ACGT"):
        return "".join(sorted(g))
    return g


def _load_terms(arg: str) -> list[str]:
    """Project terms from a file (one per line) or a comma list. Sorted, unique."""
    p = Path(arg)
    raw = p.read_text(encoding="utf-8").splitlines() if p.exists() else arg.split(",")
    terms = {t.strip() for t in raw if t.strip() and not t.strip().startswith("#")}
    return sorted(terms)


_FENCE_RE = re.compile(r"^\s*```")
_TABLE_DELIM_RE = re.compile(r"^\s*\|?\s*:?-{3,}")


# --------------------------------------------------------------------------- #
# Claim records
# --------------------------------------------------------------------------- #


@dataclass
class Claim:
    doc: str
    lineno: int
    text: str
    rsids: list[str]
    supporting_rsids: list[str]
    rsids_absent_from_index: list[str]
    has_citation: bool
    blacklist_tokens: list[str]
    clinical: bool
    project_terms: list[str]
    stated_genotype: str | None          # normalized v1-stated genotype (single-rsid lines)
    genotype_mismatch: bool | None        # None = not assessed
    missing_rsid_linkage: bool
    missing_citation: bool
    disposition: str

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        return d

    def tsv_row(self) -> str:
        return "\t".join([
            self.doc, str(self.lineno), self.disposition,
            ",".join(self.supporting_rsids), ",".join(self.rsids_absent_from_index),
            "y" if self.has_citation else "n", ",".join(self.blacklist_tokens),
            ",".join(self.project_terms),
            "" if self.genotype_mismatch is None else ("y" if self.genotype_mismatch else "n"),
            self.text.replace("\t", " "),
        ])


def _extract_claims(doc_name: str, text: str, index: dict, cite_re: re.Pattern,
                    project_terms: list[str]) -> list[Claim]:
    bl_by_line: dict[int, list[str]] = {}
    for h in find_blacklist_hits(text):
        bl_by_line.setdefault(h.lineno, []).append(h.token)

    lines = text.splitlines()
    in_frontmatter = bool(lines) and lines[0].strip() == "---"
    in_code = False
    claims: list[Claim] = []

    for i, raw in enumerate(lines, start=1):
        # leading frontmatter block
        if in_frontmatter and i > 1:
            if raw.strip() == "---":
                in_frontmatter = False
            continue
        if i == 1 and in_frontmatter:
            continue
        if _FENCE_RE.match(raw):
            in_code = not in_code
            continue
        if in_code or not raw.strip() or _TABLE_DELIM_RE.match(raw):
            continue

        rsids = extract_rsids(raw)
        gene_hits = bool(_GENE_RE.search(raw))
        clinical_noun = bool(_CLINICAL_RE.search(raw))
        bl = sorted(bl_by_line.get(i, []))
        if not (rsids or gene_hits or clinical_noun or bl):
            continue

        clinical = bool(rsids or gene_hits or clinical_noun)
        supporting = [r for r in rsids if index.get(r) and index[r][1] == "y"]
        absent = [r for r in rsids if r not in index]
        has_cite = bool(cite_re.search(raw))
        terms = sorted({t for t in project_terms if re.search(rf"\b{re.escape(t)}\b", raw, re.IGNORECASE)})

        # Subsection 8 (advisory): single rsID + single distinct genotype token.
        stated = None
        mismatch = None
        gts = {_norm_genotype(m) for m in _GENOTYPE_RE.findall(raw)}
        if len(rsids) == 1 and len(gts) == 1:
            stated = next(iter(gts))
            entry = index.get(rsids[0])
            if entry and entry[1] == "y":
                mismatch = stated != _norm_genotype(entry[0])

        if bl:
            disposition = "delete"
        elif clinical and not supporting:
            disposition = "delete"
        elif supporting and not has_cite:
            disposition = "rewrite-with-citation"
        else:
            disposition = "keep"

        claims.append(Claim(
            doc=doc_name, lineno=i, text=raw.strip(), rsids=rsids,
            supporting_rsids=supporting, rsids_absent_from_index=absent,
            has_citation=has_cite, blacklist_tokens=bl, clinical=clinical,
            project_terms=terms, stated_genotype=stated, genotype_mismatch=mismatch,
            missing_rsid_linkage=(clinical and not supporting),
            missing_citation=(clinical and not has_cite), disposition=disposition,
        ))
    return claims


def _contradictions(claims: list[Claim]) -> list[dict]:
    """Subsection 5: rsID stated with ≥2 distinct genotypes across the archive."""
    by_rsid: dict[str, dict[str, set[str]]] = {}
    for c in claims:
        if len(c.rsids) == 1 and c.stated_genotype is not None:
            by_rsid.setdefault(c.rsids[0], {}).setdefault(c.stated_genotype, set()).add(c.doc)
    out = []
    for rsid in sorted(by_rsid):
        gts = by_rsid[rsid]
        if len(gts) >= 2:
            out.append({"rsid": rsid, "genotypes": {g: sorted(docs) for g, docs in sorted(gts.items())}})
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def run_audit(archive_dir, index_path, out_dir, project_terms_arg=None) -> dict:
    archive_dir, index_path, out_dir = Path(archive_dir), Path(index_path), Path(out_dir)
    if not archive_dir.is_dir():
        die(f"archive directory not found: {archive_dir}")
    if not index_path.is_file():
        die(f"INDEX not found: {index_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    index = load_index(index_path)
    cite_re = _citation_regex()
    project_terms = _load_terms(project_terms_arg) if project_terms_arg else []

    docs_out = []
    all_claims: list[Claim] = []
    for doc in iter_archive_docs(archive_dir):
        text = doc.read_text(encoding="utf-8", errors="replace")
        claims = _extract_claims(doc.name, text, index, cite_re, project_terms)
        all_claims.extend(claims)
        docs_out.append({"doc": doc.name, "claims": [c.as_dict() for c in claims]})

    contradictions = _contradictions(all_claims)
    counts = {d: sum(1 for c in all_claims if c.disposition == d) for d in DISPOSITIONS}

    findings = {
        "index_sha256": sha256_file(index_path),
        "project_terms": project_terms,
        "summary": {
            "docs": len(docs_out),
            "claims": len(all_claims),
            "dispositions": counts,
            "contradictions": len(contradictions),
        },
        "docs": docs_out,
        "contradictions": contradictions,
    }

    (out_dir / FINDINGS_JSON).write_text(
        json.dumps(findings, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    header = ("doc\tlineno\tdisposition\tsupporting_rsids\trsids_absent\thas_citation\t"
              "blacklist_tokens\tproject_terms\tgenotype_mismatch\ttext")
    rows = [header] + [c.tsv_row() for c in sorted(all_claims, key=lambda c: (c.doc, c.lineno))]
    (out_dir / CLAIMS_TSV).write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")

    return findings


def main(argv: list[str]) -> int:
    _, flags = parse_flat_args(
        argv[1:], {"--archive", "--index", "--out", "--project-terms", "--snapshot-date"})
    for req in ("--archive", "--index", "--out"):
        if req not in flags:
            die("usage: audit.py --archive <dir> --index <INDEX.tsv> --out <dir> "
                "[--project-terms <file|csv>] [--snapshot-date YYYY-MM-DD]")
    try:
        findings = run_audit(flags["--archive"], flags["--index"], flags["--out"],
                             flags.get("--project-terms"))
    except _common.DecoderError as e:
        die(str(e))
    s = findings["summary"]
    print(json.dumps({"out": flags["--out"], **s}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
