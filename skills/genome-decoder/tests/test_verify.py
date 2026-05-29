"""Tests for verify.py (Phase 7 final verification).

Happy-path canonical docs are produced by the real renderer
(``report_render.write_report_document``) so the provenance frontmatter and the
genotype triple format are exactly what verify parses. Negative cases hand-write
minimal docs. Every fixture is synthetic — fabricated subject, rsIDs, citations.
"""

from datetime import date

import _common as C
import report_render as R
import verify
import pytest


# --------------------------------------------------------------------------- #
# Synthetic fixtures (mirroring the renderer test fixtures)
# --------------------------------------------------------------------------- #


def _prov(genome_sha, doc_id="04_Sample_Pharmacogenomics"):
    return C.ProvenanceBlock(
        doc_id=doc_id, produced_by="claude-opus-4-8[1m]", produced_on=date(2026, 1, 15),
        phase=3, source_genome_path="/data/synthetic_export.txt",
        source_genome_sha256=genome_sha, source_genome_assembly="GRCh37",
        source_genome_line_count_verified=100000,
        genotype_index_path="/data/INDEX_genotype_truth.tsv",
        genotype_index_sha256="1111111111111111", removed_claims_count=0,
        added_claims_count=1, external_sources_used=("CPIC", "dbSNP"),
        external_sources_access_date=date(2026, 1, 15),
        supersedes="/data/archive/v1/04_Sample_Pharmacogenomics.md",
        supersedes_sha256="2222222222222222",
    )


def _cpic():
    return C.Citation(source_key="cpic", label="CPIC GENE1 Guideline",
                      url="https://cpicpgx.org/guidelines/", access_date="2026-01-15")


def _dbsnp(rsid):
    return C.Citation(source_key="dbsnp", label=f"dbSNP {rsid}",
                      url=f"https://www.ncbi.nlm.nih.gov/snp/{rsid}", access_date="2026-01-15")


def _manifest():
    docs = (
        C.ReportDoc("04_Sample_Pharmacogenomics", "Pharmacogenomics Analysis",
                    "Pharmacogenomics Analysis.html", "Pharmacology", "04",
                    blurb="Genotype-guided medication response.", tier=1, available=True,
                    search_terms="pharmacogenomics", icon_token="PILL"),
    )
    return C.ReportManifest(
        subject_label="Sample Subject", report_id="HX-2026-0042", assembly="GRCh37",
        array="consumer SNP · v5", access_date="2026-01-15", sources=("CPIC", "dbSNP"),
        source_sha256="0000000000000000", supersedes="prior v1",
        supersedes_sha256="1111111111111111", docs=docs, groups=("Pharmacology",),
        stats={"documents": 1, "variants_reviewed": 1, "tier1": 1, "cpic_a": 1, "carriers": 0},
    )


def render_canonical_doc(out_dir, genome_sha, *, triple_gt="AG", rsid="rs0000001", hist=""):
    finding = C.Finding(
        gene="GENE1", name="Reduced Metabolizer", tier=1, evidence="CPIC Level A",
        triples=(C.Triple(rsid, "7", "1000000", triple_gt),),
        implication="carries one reduced-function allele per the CPIC guideline.",
        citations=(_cpic(), _dbsnp(rsid)), historical_note=hist,
    )
    rd = C.ReportDocument(
        doc_id="04_Sample_Pharmacogenomics", title="Pharmacogenomics Analysis",
        group="Pharmacology", provenance=_prov(genome_sha), findings=(finding,),
        genotype_rows=(C.GenotypeRow(C.Triple(rsid, "7", "1000000", triple_gt), "GENE1", 1),),
    )
    R.write_report_document(rd, _manifest(), out_dir=out_dir, archive_dir=out_dir / "archive")


def write_genome(tmp_path, content="# synthetic consumer DNA placeholder\n"):
    g = tmp_path / "synthetic_export.txt"
    g.write_text(content, encoding="utf-8")
    return g


def write_index(tmp_path, rows):
    """rows: iterable of (rsid, chrom, pos, genotype, found)."""
    p = tmp_path / "INDEX_genotype_truth.tsv"
    header = "rsid\tchromosome\tposition\tgenotype\tfound\tsource_docs\tdiscovered_in_phase"
    lines = [header] + ["\t".join([r, c, pos, gt, f, "doc_a.md", "0"]) for r, c, pos, gt, f in rows]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def write_prompts(tmp_path, missing=()):
    d = tmp_path / "prompts"
    d.mkdir()
    for n in range(8):
        name = f"phase{n}_prompt.md"
        if name in missing:
            continue
        (d / name).write_text(f"# Phase {n} prompt\n", encoding="utf-8")
    return d


def find(results, name):
    return next(r for r in results if r.name == name)


# --------------------------------------------------------------------------- #
# Happy path — every input supplied, every check passes, nothing skipped
# --------------------------------------------------------------------------- #


def test_all_checks_pass_with_zero_skips(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    genome = write_genome(tmp_path)
    genome_sha = C.sha256_file(genome)
    render_canonical_doc(out, genome_sha)
    index = write_index(tmp_path, [("rs0000001", "7", "1000000", "AG", "y")])
    archive = out / "archive"
    archive.mkdir()
    (archive / "v1_old.md").write_text("legacy\n", encoding="utf-8")
    prompts = write_prompts(tmp_path)

    results = verify.run_verify(
        out, index_path=index, genome_path=genome, archive_dir=archive,
        prompts_dir=prompts, expected_archive_count=1,
    )
    statuses = {r.name: r.status for r in results}
    assert all(s == "pass" for s in statuses.values()), statuses
    assert not any(r.status == "skip" for r in results), statuses
    # genotype check actually compared a citation, not a vacuous pass
    assert "1 genotype citation" in find(results, "genotype_consistency").summary


def test_archive_quoted_aspirational_and_rsid_are_exempt(tmp_path):
    """A historical note (archive-attributed blockquote) may carry hedge words and
    an out-of-INDEX rsID without failing the aspirational or traceability checks."""
    out = tmp_path / "out"
    out.mkdir()
    genome = write_genome(tmp_path)
    render_canonical_doc(
        out, C.sha256_file(genome),
        hist="the prior analysis claimed rs9999999 may benefit metabolism",
    )
    index = write_index(tmp_path, [("rs0000001", "7", "1000000", "AG", "y")])
    results = verify.run_verify(out, index_path=index, genome_path=genome)
    assert find(results, "aspirational_narrow").status == "pass"
    assert find(results, "aspirational_blacklist").status == "pass"
    assert find(results, "rsid_traceability").status == "pass"


# --------------------------------------------------------------------------- #
# Negative cases
# --------------------------------------------------------------------------- #


def test_missing_provenance_summary_fails(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "02_Notes.md").write_text("# Notes\n\nNo provenance here.\n", encoding="utf-8")
    results = verify.run_verify(out)
    cov = find(results, "provenance_coverage")
    assert cov.status == "fail"
    assert "02_Notes.md" in cov.items


def test_planted_aspirational_fails(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "02_Notes.md").write_text(
        "# Notes\n\n## Provenance Summary\n\nThis variant may benefit you.\n", encoding="utf-8"
    )
    results = verify.run_verify(out)
    assert find(results, "aspirational_narrow").status == "fail"
    assert find(results, "aspirational_blacklist").status == "fail"  # "may" is a blacklist token


def test_genome_sha_drift_fails(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    render_canonical_doc(out, genome_sha="deadbeef" * 8)  # declared sha
    other_genome = write_genome(tmp_path, content="# a different file\n")  # different live sha
    results = verify.run_verify(out, genome_path=other_genome)
    sha = find(results, "genome_sha")
    assert sha.status == "fail"
    assert any("Pharmacogenomics Analysis.md" in it for it in sha.items)


def test_genotype_mismatch_fails(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    genome = write_genome(tmp_path)
    render_canonical_doc(out, C.sha256_file(genome), triple_gt="AG")
    index = write_index(tmp_path, [("rs0000001", "7", "1000000", "GG", "y")])  # INDEX says GG
    results = verify.run_verify(out, index_path=index)
    gc = find(results, "genotype_consistency")
    assert gc.status == "fail"
    assert any("cites AG, INDEX has GG" in it for it in gc.items)


def test_untraceable_rsid_fails(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    genome = write_genome(tmp_path)
    render_canonical_doc(out, C.sha256_file(genome))
    index = write_index(tmp_path, [("rs0000002", "7", "1000000", "AG", "y")])  # rs0000001 absent
    results = verify.run_verify(out, index_path=index)
    tr = find(results, "rsid_traceability")
    assert tr.status == "fail"
    assert any("rs0000001 not in INDEX" in it for it in tr.items)


def test_found_n_rsid_is_soft_note_not_fail(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    genome = write_genome(tmp_path)
    render_canonical_doc(out, C.sha256_file(genome))
    index = write_index(tmp_path, [("rs0000001", "", "", "not_tested", "n")])  # chip-coverage gap
    results = verify.run_verify(out, index_path=index)
    tr = find(results, "rsid_traceability")
    assert tr.status == "pass"
    assert any("found=n" in it for it in tr.items)


def test_missing_continuation_prompt_fails(tmp_path):
    prompts = write_prompts(tmp_path, missing=("phase7_prompt.md",))
    out = tmp_path / "out"
    out.mkdir()
    results = verify.run_verify(out, prompts_dir=prompts)
    cp = find(results, "continuation_prompts")
    assert cp.status == "fail"
    assert "phase7_prompt.md" in cp.items


def test_expected_archive_count_mismatch_fails(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    archive = out / "archive"
    archive.mkdir()
    (archive / "a.md").write_text("x\n", encoding="utf-8")
    results = verify.run_verify(out, archive_dir=archive, expected_archive_count=5)
    assert find(results, "archive_integrity").status == "fail"


# --------------------------------------------------------------------------- #
# Skip semantics + determinism
# --------------------------------------------------------------------------- #


def test_missing_inputs_are_skipped_loudly(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    results = verify.run_verify(out)  # only --out
    skipped = {r.name for r in results if r.status == "skip"}
    assert skipped == {"archive_integrity", "genome_sha", "rsid_traceability",
                       "genotype_consistency", "continuation_prompts"}


def test_report_is_deterministic(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    genome = write_genome(tmp_path)
    render_canonical_doc(out, C.sha256_file(genome))
    index = write_index(tmp_path, [("rs0000001", "7", "1000000", "AG", "y")])
    r1 = verify.render_report(verify.run_verify(out, index_path=index, genome_path=genome))
    r2 = verify.render_report(verify.run_verify(out, index_path=index, genome_path=genome))
    assert r1 == r2
    assert "date" not in r1.lower()  # no wall-clock leakage
