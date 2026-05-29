#!/usr/bin/env python3
"""discover.py — Phase 6 net-new findings scan (SPEC Phase 6 Scan A–E).

It **confirms, filters, dedups, and verifies** an agent-supplied reference set
against the source genome, then emits a deterministic candidate set. It does NOT
discover candidates from the network (the allow-list endpoints fetch a named
record, not a search), assign clinical tier (1/2/3), resolve allele-strand
orientation, author any document, or mutate the canonical Phase-0 INDEX. Those
are agent-side or Phase-boundary work.

Inputs the tool derives (never supplied):
  * ``chromosome`` / ``position`` / ``genotype`` / ``found`` — one batched
    ``lookup.py --columns`` substrate call over the candidate-rsID union;
  * allele match + ``strand_assumption`` (direct / complement);
  * pass membership A / B / C; Phase-0 dedup; ``net_new`` (grep); ``url_verified``.

Reference the caller supplies (domain facts the tool cannot compute):
  * ``--clinvar`` TSV: ``rsid  pathogenic_allele  gene  vcv  significance``;
  * ``--cpic``    TSV: ``gene  drug  level  defining_rsids``;
  * the ACMG SF v3.2 reportable gene list is a pinned constant below.

Passes (a candidate must be ``found == "y"``):
  * **C** — a CPIC Level A/B defining rsID present in the genome.
  * **A** — a ClinVar Pathogenic / Likely-pathogenic rsID present in the genome
    whose genotype carries the pathogenic allele (direct or complement strand).
  * **B** — the subset of A whose gene is on the ACMG SF v3.2 list.

The union (A ∪ B ∪ C) minus rsIDs already in the Phase-0 INDEX is the candidate
set, sorted by rsID. For each candidate ``fetch_allowed`` records ``url_verified``
— this means only that the citation URL resolved on the snapshot date; it is NOT
confirmation of pathogenicity or of the reference's claims.

CLI::

    discover.py <source_genome> --index <INDEX.tsv> --out <dir>
                --snapshot-date YYYY-MM-DD --archive-flagship <path>
                [--clinvar <file>] [--cpic <file>] [--allow-network]

Outputs (deterministic, only date is ``--snapshot-date``):
  * ``phase6_candidates.tsv`` — INDEX-shaped rows ready to append.
  * ``phase6_findings.json``  — per-candidate provenance + counts + a run log.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import _common
from _common import (
    LOOKUP_COLUMNS,
    NOT_TESTED,
    SubstrateError,
    die,
    fetch_allowed,
    genotype_found,
    parse_flat_args,
    parse_snapshot_date,
    sha256_file,
)

# ACMG SF v3.2 (Miller et al., 2023) reportable secondary-findings gene list.
# Pinned constant — edit here when ACMG revises the list. Membership only labels
# pass B; the agent reviews. Verify against the official publication before a run.
ACMG_SF_V3_2 = frozenset({
    # Hereditary cancer
    "APC", "BMPR1A", "BRCA1", "BRCA2", "CDH1", "MAX", "MEN1", "MLH1", "MSH2",
    "MSH6", "MUTYH", "NF2", "PALB2", "PMS2", "PTEN", "RB1", "RET", "SDHAF2",
    "SDHB", "SDHC", "SDHD", "SMAD4", "STK11", "TMEM127", "TP53", "TSC1", "TSC2",
    "VHL", "WT1",
    # Cardiovascular
    "ACTA2", "ACTC1", "APOB", "BAG3", "CACNA1S", "COL3A1", "DES", "DSC2", "DSG2",
    "DSP", "FBN1", "FLNC", "GLA", "KCNH2", "KCNQ1", "LDLR", "LMNA", "MYBPC3",
    "MYH11", "MYH7", "MYL2", "MYL3", "PCSK9", "PKP2", "PLN", "PRKAG2", "RBM20",
    "RYR2", "SCN5A", "SMAD3", "TGFBR1", "TGFBR2", "TMEM43", "TNNC1", "TNNI3",
    "TNNT2", "TPM1", "TTN", "TTR", "ACVRL1", "ENG", "CASQ2", "TRDN",
    # Metabolic / other
    "ATP7B", "BTD", "GAA", "HFE", "HNF1A", "OTC", "RPE65", "RYR1",
})
ACMG_SF_VERSION = "ACMG SF v3.2 (2023)"

_PATHOGENIC = {"pathogenic", "likely pathogenic"}
_COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C"}

CANDIDATES_TSV = "phase6_candidates.tsv"
FINDINGS_JSON = "phase6_findings.json"
POOL_FILENAME = "phase6_rsid_pool.txt"
INDEX_COLUMNS = ("rsid", "chromosome", "position", "genotype", "found",
                 "source_docs", "discovered_in_phase")
SOURCE_DOCS = "phase6_discovery"
DISCOVERED_IN_PHASE = "6"
_RSID_RE = re.compile(r"rs\d+")


# --------------------------------------------------------------------------- #
# Reference + INDEX loaders
# --------------------------------------------------------------------------- #


def _read_tsv(path: Path) -> tuple[list[str], list[list[str]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise _common.DecoderError(f"empty reference file: {path}")
    return lines[0].split("\t"), [ln.split("\t") for ln in lines[1:] if ln.strip()]


def load_phase0_rsids(index_path: Path) -> set[str]:
    header, rows = _read_tsv(index_path)
    try:
        i = header.index("rsid")
    except ValueError as e:
        raise _common.DecoderError(f"INDEX missing 'rsid' column: {e}") from e
    return {r[i] for r in rows if len(r) > i and r[i]}


def load_clinvar(path: Path, log: list[str]) -> list[dict]:
    header, rows = _read_tsv(path)
    need = ("rsid", "pathogenic_allele", "gene", "vcv", "significance")
    idx = {c: header.index(c) for c in need if c in header}
    missing = [c for c in need if c not in idx]
    if missing:
        raise _common.DecoderError(f"--clinvar missing column(s): {','.join(missing)}")
    out, skipped = [], 0
    for r in rows:
        if len(r) <= max(idx.values()):
            continue
        if r[idx["significance"]].strip().lower() not in _PATHOGENIC:
            skipped += 1
            continue
        out.append({k: r[idx[k]].strip() for k in need})
    if skipped:
        log.append(f"clinvar: skipped {skipped} row(s) not Pathogenic/Likely pathogenic")
    return out


def load_cpic(path: Path, log: list[str]) -> dict[str, dict]:
    header, rows = _read_tsv(path)
    need = ("gene", "drug", "level", "defining_rsids")
    idx = {c: header.index(c) for c in need if c in header}
    missing = [c for c in need if c not in idx]
    if missing:
        raise _common.DecoderError(f"--cpic missing column(s): {','.join(missing)}")
    genes: dict[str, dict] = {}
    skipped = 0
    for r in rows:
        if len(r) <= max(idx.values()):
            continue
        level = _norm_level(r[idx["level"]])
        if level is None:
            skipped += 1
            continue
        gene = r[idx["gene"]].strip()
        rsids = [m for m in _RSID_RE.findall(r[idx["defining_rsids"]])]
        g = genes.setdefault(gene, {"levels": set(), "drugs": set(), "rsids": set()})
        g["levels"].add(level)
        g["drugs"].add(r[idx["drug"]].strip())
        g["rsids"].update(rsids)
    if skipped:
        log.append(f"cpic: skipped {skipped} row(s) not Level A/B")
    return genes


def _norm_level(s: str) -> str | None:
    s = s.strip().upper()
    if s in ("A", "LEVEL A"):
        return "A"
    if s in ("B", "LEVEL B"):
        return "B"
    return None


# --------------------------------------------------------------------------- #
# Substrate + matching
# --------------------------------------------------------------------------- #


def _lookup_genotypes(genome: Path, rsids: list[str], out_dir: Path) -> dict[str, tuple[str, str, str]]:
    if not rsids:
        return {}
    pool = out_dir / POOL_FILENAME
    pool.write_text("\n".join(rsids) + "\n", encoding="utf-8", newline="\n")
    tsv = _common.run_substrate("lookup.py", str(genome), "--rsids", str(pool),
                                "--columns", LOOKUP_COLUMNS)
    lines = tsv.splitlines()
    if not lines or lines[0].split("\t") != LOOKUP_COLUMNS.split(","):
        raise SubstrateError(
            f"lookup.py header {lines[0] if lines else '<empty>'!r} != {LOOKUP_COLUMNS}")
    rows: dict[str, tuple[str, str, str]] = {}
    for ln in lines[1:]:
        if not ln.strip():
            continue
        parts = ln.split("\t")
        if len(parts) != 4:
            raise SubstrateError(f"malformed lookup.py row: {ln!r}")
        rows[parts[0]] = (parts[1], parts[2], parts[3])
    return rows


def _allele_match(genotype: str, allele: str) -> tuple[bool | None, str]:
    """(matched, strand). matched is None for a non-SNV allele (agent assesses)."""
    a = allele.strip().upper()
    if len(a) != 1 or a not in "ACGT":
        return (None, "unmatched")
    alleles = set(genotype.upper())
    if a in alleles:
        return (True, "direct")
    if _COMPLEMENT[a] in alleles:
        return (True, "complement")
    return (False, "none")


def _grep_count(rsid: str, flagship_text: str) -> int:
    return len(re.findall(r"\b" + re.escape(rsid) + r"\b", flagship_text))


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def run_discover(genome, index_path, out_dir, snapshot_date, archive_flagship,
                 clinvar_path=None, cpic_path=None, allow_network=False) -> dict:
    genome, index_path, out_dir = Path(genome), Path(index_path), Path(out_dir)
    archive_flagship = Path(archive_flagship)
    if not genome.exists():
        die(f"source genome not found: {genome}")
    if not index_path.is_file():
        die(f"INDEX not found: {index_path}")
    if not archive_flagship.is_file():
        die(f"archive flagship not found: {archive_flagship}")
    if not clinvar_path and not cpic_path:
        die("at least one of --clinvar / --cpic is required")
    out_dir.mkdir(parents=True, exist_ok=True)

    log: list[str] = []
    phase0 = load_phase0_rsids(index_path)
    clinvar = load_clinvar(Path(clinvar_path), log) if clinvar_path else []
    cpic = load_cpic(Path(cpic_path), log) if cpic_path else {}
    if not clinvar_path:
        log.append("clinvar: input not provided — passes A/B empty")
    if not cpic_path:
        log.append("cpic: input not provided — pass C empty")

    # rsID universe
    clinvar_by_rsid: dict[str, list[dict]] = {}
    for row in clinvar:
        clinvar_by_rsid.setdefault(row["rsid"], []).append(row)
    cpic_ab_genes = {g: d for g, d in cpic.items() if d["levels"]}
    cpic_rsid_gene: dict[str, set[str]] = {}
    for gene, d in cpic_ab_genes.items():
        for rsid in d["rsids"]:
            cpic_rsid_gene.setdefault(rsid, set()).add(gene)
    universe = sorted(set(clinvar_by_rsid) | set(cpic_rsid_gene))
    log.append(f"scan scope: clinvar_rsids={len(clinvar_by_rsid)} "
               f"cpic_AB_genes={len(cpic_ab_genes)} acmg_genes={len(ACMG_SF_V3_2)} "
               f"universe_rsids={len(universe)}")

    genotypes = _lookup_genotypes(genome, universe, out_dir)
    flagship_text = archive_flagship.read_text(encoding="utf-8", errors="replace")

    candidates: list[dict] = []
    dropped_phase0 = 0
    for rsid in universe:
        chrom, pos, genotype = genotypes.get(rsid, ("", "", NOT_TESTED))
        if not genotype_found(genotype):
            continue
        if rsid in phase0:
            dropped_phase0 += 1
            continue

        passes: set[str] = set()
        clinvar_prov: list[dict] = []
        for row in clinvar_by_rsid.get(rsid, []):
            matched, strand = _allele_match(genotype, row["pathogenic_allele"])
            if matched is False:
                continue  # subject does not carry this SNV pathogenic allele
            passes.add("A")
            if row["gene"] in ACMG_SF_V3_2:
                passes.add("B")
            cit = _citation("clinvar", row["vcv"], out_dir, snapshot_date, allow_network)
            clinvar_prov.append({
                "vcv": row["vcv"], "gene": row["gene"],
                "significance": row["significance"],
                "pathogenic_allele": row["pathogenic_allele"],
                "allele_matched": matched, "strand_assumption": strand,
                "citation": cit,
            })
        # If every ClinVar row for this rsID was a non-carrier SNV, clinvar_prov is
        # empty and pass A/B were not added (the rsID may still qualify via pass C).

        cpic_prov: list[dict] = []
        for gene in sorted(cpic_rsid_gene.get(rsid, set())):
            passes.add("C")
            d = cpic_ab_genes[gene]
            cit = _citation("cpic", gene, out_dir, snapshot_date, allow_network)
            cpic_prov.append({
                "gene": gene, "level": sorted(d["levels"]),
                "drugs": sorted(d["drugs"]), "citation": cit,
            })

        if not passes:
            continue  # no pass confirmed (e.g. ClinVar SNV non-carrier only)

        observed = _grep_count(rsid, flagship_text)
        candidates.append({
            "rsid": rsid, "chromosome": chrom, "position": pos, "genotype": genotype,
            "found": "y", "passes": sorted(passes),
            "net_new": observed == 0,
            "grep": {"pattern": rsid, "glob": str(archive_flagship),
                     "expected": 0, "observed": observed},
            "clinvar": sorted(clinvar_prov, key=lambda c: c["vcv"]),
            "cpic": cpic_prov,
        })

    candidates.sort(key=lambda c: c["rsid"])

    findings = {
        "_url_verified_note": ("url_verified means the citation URL resolved on "
                               "snapshot_date only; it is NOT pathogenicity confirmation."),
        "snapshot_date": snapshot_date.isoformat(),
        "phase0_index_sha256": sha256_file(index_path),
        "clinvar_ref_sha256": sha256_file(clinvar_path) if clinvar_path else None,
        "cpic_ref_sha256": sha256_file(cpic_path) if cpic_path else None,
        "acmg_sf_version": ACMG_SF_VERSION,
        "summary": {
            "candidates": len(candidates),
            "dropped_phase0": dropped_phase0,
            "net_new": sum(1 for c in candidates if c["net_new"]),
        },
        "candidates": candidates,
        "log": log,
    }

    (out_dir / FINDINGS_JSON).write_text(
        json.dumps(findings, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    rows = ["\t".join(INDEX_COLUMNS)]
    for c in candidates:
        rows.append("\t".join([c["rsid"], c["chromosome"], c["position"], c["genotype"],
                               "y", SOURCE_DOCS, DISCOVERED_IN_PHASE]))
    (out_dir / CANDIDATES_TSV).write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    return findings


def _citation(source_key: str, identifier: str, out_dir: Path, snapshot_date, allow_network) -> dict:
    fr = fetch_allowed(source_key, identifier, out_dir, snapshot_date, allow_network=allow_network)
    return {"source_key": source_key, "identifier": identifier,
            "url": fr.url, "url_verified": fr.url_verified}


def main(argv: list[str]) -> int:
    positionals, flags = parse_flat_args(
        argv[1:],
        {"--index", "--out", "--snapshot-date", "--archive-flagship", "--clinvar", "--cpic"},
        bool_flags={"--allow-network"},
    )
    if not positionals or "--index" not in flags or "--out" not in flags \
            or "--snapshot-date" not in flags or "--archive-flagship" not in flags:
        die("usage: discover.py <source_genome> --index <INDEX.tsv> --out <dir> "
            "--snapshot-date YYYY-MM-DD --archive-flagship <path> "
            "[--clinvar <file>] [--cpic <file>] [--allow-network]")
    snapshot_date = parse_snapshot_date(flags)
    try:
        findings = run_discover(
            positionals[0], flags["--index"], flags["--out"], snapshot_date,
            flags["--archive-flagship"], clinvar_path=flags.get("--clinvar"),
            cpic_path=flags.get("--cpic"), allow_network="--allow-network" in flags,
        )
    except _common.DecoderError as e:
        die(str(e))
    print(json.dumps({"out": flags["--out"], **findings["summary"], "log": findings["log"]},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
