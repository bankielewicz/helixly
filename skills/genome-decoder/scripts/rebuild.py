#!/usr/bin/env python3
"""rebuild.py — agent↔renderer assembly bridge (Phases 2–7).

Turns **agent-authored structured content** (JSON specs) into rendered HelixyAI
documents by constructing the ``_common`` typed objects and writing them through
the existing gated path (``report_render.write_report_document`` /
``write_report_index``). It authors and invents nothing: every clinical assertion
originates in the agent's spec. It makes no network call and runs no substrate.

Safety is by construction. The foundation dataclasses validate on construction —
an off-allow-list ``Citation`` raises ``AllowlistError``, a ``Finding`` without a
``Triple``+``Citation`` raises, an incomplete ``ProvenanceBlock`` raises (SPEC
Rule 6). The write path enforces the rest — the ``## Provenance Summary``, the
aspirational-phrase blacklist gate on the markdown twin (Rule 1c), the archive
guard (Rule 9), and the always-emitted "consult your prescribing clinician"
disclaimer (Rule 5). rebuild.py adds no new claim path, so it cannot weaken a gate.

Actions::

    rebuild.py document  --doc <doc.json> --manifest <manifest.json> --out <dir> --archive <dir>
    rebuild.py index     --manifest <manifest.json> --out <dir> [--archive <dir>]
    rebuild.py checklist --phase 3|4 [--index <INDEX.tsv>]
    rebuild.py context   --project-context <md>

The Phase-3 pharmacogene panel and Phase-4 methylation checklist are SPEC-fixed
constants. Phase 5 is not hardcoded (per the skill's generalization): a project
context is loaded from a passed-in markdown file.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import _common as C
import report_render
from _common import die, parse_flat_args, warn

# SPEC Phase 3 — fixed in-scope pharmacogene panel (gene-level).
PHASE3_PHARMACOGENES = (
    "CYP2D6", "CYP2C19", "CYP2C9", "CYP1A2", "CYP3A4", "CYP3A5", "VKORC1", "TPMT",
    "NUDT15", "NAT2", "UGT1A1", "SLCO1B1", "DPYD",
)

# SPEC Phase 4 — fixed methylation rsID checklist (gene → defining rsIDs), in
# SPEC order so the printed checklist is deterministic.
PHASE4_METHYLATION = {
    "MTHFR": ("rs1801133", "rs1801131"),
    "MTR": ("rs1805087",),
    "MTRR": ("rs1801394",),
    "CBS": ("rs5742905", "rs234706"),
    "BHMT": ("rs3733890",),
    "AHCY": ("rs819147",),
    "SHMT1": ("rs1979277",),
    "MAT1A": ("rs17421511",),
    "TYMS": ("rs502396",),
}


# --------------------------------------------------------------------------- #
# Spec → typed objects
# --------------------------------------------------------------------------- #


def _req(d: dict, key: str):
    if not isinstance(d, dict) or key not in d or d[key] in (None, ""):
        raise C.DecoderError(f"spec missing required field: {key!r}")
    return d[key]


def _maybe_int(v):
    """Coerce a present value to int; pass None/'' through so the dataclass
    validation produces the clear 'field empty' error instead of int(None)."""
    return int(v) if v not in (None, "") else v


def _triple(d: dict) -> C.Triple:
    return C.Triple(rsid=_req(d, "rsid"), chrom=str(_req(d, "chrom")),
                    pos=str(_req(d, "pos")), genotype=_req(d, "genotype"))


def _citation(d: dict) -> C.Citation:
    return C.Citation(source_key=_req(d, "source_key"), label=_req(d, "label"),
                      url=_req(d, "url"), access_date=str(_req(d, "access_date")))


def _finding(d: dict) -> C.Finding:
    return C.Finding(
        gene=_req(d, "gene"), name=_req(d, "name"), tier=_maybe_int(_req(d, "tier")),
        evidence=_req(d, "evidence"),
        triples=tuple(_triple(t) for t in d.get("triples", [])),
        implication=_req(d, "implication"),
        citations=tuple(_citation(c) for c in d.get("citations", [])),
        subtitle=d.get("subtitle", ""), historical_note=d.get("historical_note", ""),
    )


def _alert_row(d: dict) -> C.AlertRow:
    return C.AlertRow(
        drug=_req(d, "drug"), gene_genotype=_req(d, "gene_genotype"),
        evidence=_req(d, "evidence"), recommendation=_req(d, "recommendation"),
        citation=_citation(_req(d, "citation")),
    )


def _genotype_row(d: dict) -> C.GenotypeRow:
    return C.GenotypeRow(
        triple=C.Triple(rsid=_req(d, "rsid"), chrom=str(_req(d, "chrom")),
                        pos=str(_req(d, "pos")), genotype=_req(d, "genotype")),
        gene=_req(d, "gene"), tier=_maybe_int(_req(d, "tier")),
    )


def _date(d: dict, key: str):
    v = d.get(key)
    if not v:
        return None  # let ProvenanceBlock raise the 'field empty' error
    try:
        return date.fromisoformat(v)
    except ValueError as e:
        raise C.DecoderError(f"provenance.{key} must be YYYY-MM-DD: {e}") from e


def _provenance(d: dict) -> C.ProvenanceBlock:
    return C.ProvenanceBlock(
        doc_id=d.get("doc_id"), produced_by=d.get("produced_by"),
        produced_on=_date(d, "produced_on"), phase=_maybe_int(d.get("phase")),
        source_genome_path=d.get("source_genome_path"),
        source_genome_sha256=d.get("source_genome_sha256"),
        source_genome_assembly=d.get("source_genome_assembly"),
        source_genome_line_count_verified=_maybe_int(d.get("source_genome_line_count_verified")),
        genotype_index_path=d.get("genotype_index_path"),
        genotype_index_sha256=d.get("genotype_index_sha256"),
        removed_claims_count=_maybe_int(d.get("removed_claims_count")),
        added_claims_count=_maybe_int(d.get("added_claims_count")),
        external_sources_used=tuple(d.get("external_sources_used") or ()),
        external_sources_access_date=_date(d, "external_sources_access_date"),
        supersedes=d.get("supersedes"), supersedes_sha256=d.get("supersedes_sha256"),
    )


def build_document(spec: dict) -> C.ReportDocument:
    return C.ReportDocument(
        doc_id=_req(spec, "doc_id"), title=_req(spec, "title"), group=_req(spec, "group"),
        provenance=_provenance(_req(spec, "provenance")),
        kicker=spec.get("kicker", ""), subtitle=spec.get("subtitle", ""),
        facts=tuple(spec.get("facts") or ()),
        alert_rows=tuple(_alert_row(a) for a in spec.get("alert_rows", [])),
        findings=tuple(_finding(f) for f in spec.get("findings", [])),
        genotype_rows=tuple(_genotype_row(g) for g in spec.get("genotype_rows", [])),
    )


def _report_doc(d: dict) -> C.ReportDoc:
    return C.ReportDoc(
        doc_id=_req(d, "doc_id"), title=_req(d, "title"), filename=_req(d, "filename"),
        group=_req(d, "group"), number=str(_req(d, "number")),
        blurb=d.get("blurb", ""), tier_summary=d.get("tier_summary", ""),
        tier=int(d.get("tier", 0)), findings_label=d.get("findings_label", ""),
        available=bool(d.get("available", False)), search_terms=d.get("search_terms", ""),
        icon_token=d.get("icon_token", "NODE"),
    )


def build_manifest(spec: dict) -> C.ReportManifest:
    return C.ReportManifest(
        subject_label=_req(spec, "subject_label"), report_id=_req(spec, "report_id"),
        assembly=_req(spec, "assembly"), array=spec.get("array", ""),
        access_date=_req(spec, "access_date"),
        sources=tuple(spec.get("sources") or ()), source_sha256=spec.get("source_sha256", ""),
        supersedes=spec.get("supersedes", ""), supersedes_sha256=spec.get("supersedes_sha256", ""),
        docs=tuple(_report_doc(d) for d in spec.get("docs", [])),
        groups=tuple(spec.get("groups") or ()), stats=spec.get("stats", {}),
        build_label=spec.get("build_label", "genome-decoder"),
    )


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_document(doc_path, manifest_path, out_dir, archive_dir) -> dict:
    manifest = build_manifest(_load_json(manifest_path))
    rd = build_document(_load_json(doc_path))
    if manifest.doc_index(rd.doc_id) < 0:
        warn(f"doc_id {rd.doc_id!r} is not in manifest.docs; the renderer will fall "
             f"back to a '<title>.html' filename")
    return report_render.write_report_document(rd, manifest, out_dir=out_dir, archive_dir=archive_dir)


def write_index(manifest_path, out_dir, archive_dir=None) -> dict:
    manifest = build_manifest(_load_json(manifest_path))
    return report_render.write_report_index(manifest, out_dir=out_dir, archive_dir=archive_dir)


def _load_index_found(index_path: Path) -> dict[str, str]:
    """INDEX TSV → ``{rsid: found}`` keyed by header name."""
    lines = index_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise C.DecoderError(f"empty INDEX: {index_path}")
    header = lines[0].split("\t")
    try:
        i_rsid, i_found = header.index("rsid"), header.index("found")
    except ValueError as e:
        raise C.DecoderError(f"INDEX missing required column: {e}") from e
    out = {}
    for ln in lines[1:]:
        if not ln.strip():
            continue
        cols = ln.split("\t")
        if len(cols) > max(i_rsid, i_found):
            out[cols[i_rsid]] = cols[i_found]
    return out


def checklist_report(phase: str, index_path=None) -> str:
    if phase == "3":
        lines = [f"Phase 3 pharmacogenes ({len(PHASE3_PHARMACOGENES)}) — gene-level:"]
        lines += [f"  {g}" for g in PHASE3_PHARMACOGENES]
        return "\n".join(lines) + "\n"
    if phase == "4":
        index = _load_index_found(Path(index_path)) if index_path else None
        lines = ["Phase 4 methylation checklist (gene\trsid[\tfound]):"]
        for gene, rsids in PHASE4_METHYLATION.items():
            for rsid in rsids:
                suffix = ""
                if index is not None:
                    suffix = f"\t{index[rsid]}" if rsid in index else "\t? (absent from INDEX)"
                lines.append(f"  {gene}\t{rsid}{suffix}")
        return "\n".join(lines) + "\n"
    die("checklist --phase must be 3 or 4")


def load_project_context(md_path) -> dict:
    """Parse a Phase-5 project-context markdown leniently (no typed schema, N=1).

    Splits on ``## `` headings; preserves the timeline section verbatim (SPEC
    Phase 5); surfaces every rsID for the agent to drive its analysis.
    """
    text = Path(md_path).read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    cur, buf = None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur is not None:
                sections[cur] = "\n".join(buf).strip()
            cur, buf = line[3:].strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        sections[cur] = "\n".join(buf).strip()
    timeline = next((b for h, b in sections.items() if "timeline" in h.lower()), "")
    return {"sections": sections, "timeline": timeline,
            "checklist_rsids": C.extract_rsids(text)}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

_USAGE = (
    "usage:\n"
    "  rebuild.py document  --doc <doc.json> --manifest <manifest.json> --out <dir> --archive <dir>\n"
    "  rebuild.py index     --manifest <manifest.json> --out <dir> [--archive <dir>]\n"
    "  rebuild.py checklist --phase 3|4 [--index <INDEX.tsv>]\n"
    "  rebuild.py context   --project-context <md>"
)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        die(_USAGE)
    action = argv[1]
    _, flags = parse_flat_args(
        argv[2:],
        {"--doc", "--manifest", "--out", "--archive", "--index", "--phase", "--project-context"},
    )
    try:
        if action == "document":
            for r in ("--doc", "--manifest", "--out", "--archive"):
                if r not in flags:
                    die(_USAGE)
            res = write_document(flags["--doc"], flags["--manifest"], flags["--out"], flags["--archive"])
            print(json.dumps(res, indent=2, sort_keys=True))
        elif action == "index":
            for r in ("--manifest", "--out"):
                if r not in flags:
                    die(_USAGE)
            res = write_index(flags["--manifest"], flags["--out"], flags.get("--archive"))
            print(json.dumps(res, indent=2, sort_keys=True))
        elif action == "checklist":
            if "--phase" not in flags:
                die(_USAGE)
            sys.stdout.write(checklist_report(flags["--phase"], flags.get("--index")))
        elif action == "context":
            if "--project-context" not in flags:
                die(_USAGE)
            print(json.dumps(load_project_context(flags["--project-context"]), indent=2, sort_keys=True))
        else:
            die(_USAGE)
    except C.DecoderError as e:
        die(str(e))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
