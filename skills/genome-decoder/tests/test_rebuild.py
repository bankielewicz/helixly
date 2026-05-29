"""Tests for rebuild.py (agent↔renderer assembly bridge).

No network, no substrate. Builds typed objects from synthetic JSON specs and
writes through the gated renderer. Every subject, rsID, gene, and citation is
synthetic.
"""

import json

import _common as C
import rebuild
import pytest


# --------------------------------------------------------------------------- #
# Synthetic specs
# --------------------------------------------------------------------------- #


def manifest_spec():
    return {
        "subject_label": "Sample Subject", "report_id": "HX-2026-0042",
        "assembly": "GRCh37", "array": "consumer SNP · v5", "access_date": "2026-01-15",
        "sources": ["CPIC", "dbSNP"], "source_sha256": "0" * 16,
        "supersedes": "prior v1", "supersedes_sha256": "1" * 16,
        "groups": ["Pharmacology"], "build_label": "genome-decoder",
        "stats": {"documents": 1, "variants_reviewed": 1, "tier1": 1, "cpic_a": 1, "carriers": 0},
        "docs": [{
            "doc_id": "04_PGx", "title": "Pharmacogenomics Analysis",
            "filename": "Pharmacogenomics Analysis.html", "group": "Pharmacology",
            "number": "04", "blurb": "Genotype-guided medication response.",
            "tier": 1, "available": True, "search_terms": "pharmacogenomics",
            "icon_token": "PILL",
        }],
    }


def provenance_spec():
    return {
        "doc_id": "04_PGx", "produced_by": "claude-opus-4-8[1m]", "produced_on": "2026-01-15",
        "phase": 3, "source_genome_path": "/data/synthetic_export.txt",
        "source_genome_sha256": "0" * 16, "source_genome_assembly": "GRCh37",
        "source_genome_line_count_verified": 100000,
        "genotype_index_path": "/data/INDEX_genotype_truth.tsv",
        "genotype_index_sha256": "1" * 16, "removed_claims_count": 0, "added_claims_count": 1,
        "external_sources_used": ["CPIC", "dbSNP"], "external_sources_access_date": "2026-01-15",
        "supersedes": "/data/archive/v1/04_PGx.md", "supersedes_sha256": "2" * 16,
    }


def cpic_cite():
    return {"source_key": "cpic", "label": "CPIC GENE1 Guideline",
            "url": "https://cpicpgx.org/guidelines/", "access_date": "2026-01-15"}


def dbsnp_cite(rsid="rs0000001"):
    return {"source_key": "dbsnp", "label": f"dbSNP {rsid}",
            "url": f"https://www.ncbi.nlm.nih.gov/snp/{rsid}", "access_date": "2026-01-15"}


def doc_spec(implication="carries one reduced-function allele per the CPIC guideline."):
    return {
        "doc_id": "04_PGx", "title": "Pharmacogenomics Analysis", "group": "Pharmacology",
        "kicker": "Pharmacology · Document 04", "subtitle": "Genotype and medication response.",
        "facts": ["1 finding", "1 Tier 1"], "provenance": provenance_spec(),
        "alert_rows": [{
            "drug": "ExampleDrug A", "gene_genotype": "GENE1 *2/*2 (rs0000001 AG)",
            "evidence": "CPIC Level A",
            "recommendation": "Reduced function — consider an alternative; consult your prescribing clinician.",
            "citation": cpic_cite(),
        }],
        "findings": [{
            "gene": "GENE1", "name": "Reduced Metabolizer", "tier": 1, "evidence": "CPIC Level A",
            "subtitle": "Cytochrome P450 family", "implication": implication,
            "triples": [{"rsid": "rs0000001", "chrom": "7", "pos": "1000000", "genotype": "AG"}],
            "citations": [cpic_cite(), dbsnp_cite()],
        }],
        "genotype_rows": [{"rsid": "rs0000001", "chrom": "7", "pos": "1000000",
                           "genotype": "AG", "gene": "GENE1", "tier": 1}],
    }


def write_specs(tmp_path, doc=None, manifest=None):
    d = tmp_path / "doc.json"
    m = tmp_path / "manifest.json"
    d.write_text(json.dumps(doc or doc_spec()), encoding="utf-8")
    m.write_text(json.dumps(manifest or manifest_spec()), encoding="utf-8")
    return d, m


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def test_build_document_constructs_typed_objects():
    rd = rebuild.build_document(doc_spec())
    assert isinstance(rd, C.ReportDocument)
    assert rd.provenance.phase == 3
    assert rd.findings[0].triples[0].rsid == "rs0000001"
    assert rd.findings[0].citations[0].source_key == "cpic"


def test_build_manifest_constructs_typed_objects():
    m = rebuild.build_manifest(manifest_spec())
    assert isinstance(m, C.ReportManifest)
    assert m.docs[0].doc_id == "04_PGx"
    assert m.groups == ("Pharmacology",)


def test_write_document_writes_gated_md_and_html(tmp_path):
    d, m = write_specs(tmp_path)
    out = tmp_path / "out"
    res = rebuild.write_document(d, m, out, out / "archive")
    md = (out / "Pharmacogenomics Analysis.md").read_text(encoding="utf-8")
    assert (out / "Pharmacogenomics Analysis.html").exists()
    assert "## Provenance Summary" in md
    assert "rs0000001" in md
    assert "prescribing clinician" in md  # Rule 5 disclaimer always emitted


def test_write_index(tmp_path):
    _, m = write_specs(tmp_path)
    out = tmp_path / "out"
    rebuild.write_index(m, out)
    assert (out / "index.html").exists()


# --------------------------------------------------------------------------- #
# Gates fire through the bridge
# --------------------------------------------------------------------------- #


def test_offlist_citation_raises():
    spec = doc_spec()
    spec["findings"][0]["citations"][0]["source_key"] = "notreal"
    with pytest.raises(C.AllowlistError):
        rebuild.build_document(spec)


def test_aspirational_implication_blocked_on_write(tmp_path):
    d, m = write_specs(tmp_path, doc=doc_spec(implication="this variant may benefit your metabolism."))
    with pytest.raises(C.AspirationalClaimDetected):
        rebuild.write_document(d, m, tmp_path / "out", tmp_path / "out" / "archive")


def test_incomplete_provenance_raises():
    spec = doc_spec()
    del spec["provenance"]["source_genome_sha256"]
    with pytest.raises(C.IncompleteProvenanceError):
        rebuild.build_document(spec)


def test_finding_without_triple_raises():
    spec = doc_spec()
    spec["findings"][0]["triples"] = []
    with pytest.raises(C.DecoderError):
        rebuild.build_document(spec)


def test_missing_required_field_raises():
    spec = doc_spec()
    del spec["title"]
    with pytest.raises(C.DecoderError, match="title"):
        rebuild.build_document(spec)


# --------------------------------------------------------------------------- #
# Fixed checklists + project context
# --------------------------------------------------------------------------- #


def test_phase3_checklist_lists_genes():
    out = rebuild.checklist_report("3")
    for gene in rebuild.PHASE3_PHARMACOGENES:
        assert gene in out
    assert len(rebuild.PHASE3_PHARMACOGENES) == 13


def test_phase4_checklist_with_index_marks_found(tmp_path):
    idx = tmp_path / "INDEX.tsv"
    idx.write_text(
        "rsid\tchromosome\tposition\tgenotype\tfound\tsource_docs\tdiscovered_in_phase\n"
        "rs1801133\t1\t100\tAG\ty\td.md\t0\n"
        "rs1801131\t1\t200\t--\tn\td.md\t0\n",
        encoding="utf-8",
    )
    out = rebuild.checklist_report("4", str(idx))
    assert "rs1801133\ty" in out          # found on chip
    assert "rs1801131\tn" in out          # chip-coverage gap
    assert "rs1805087\t? (absent from INDEX)" in out  # not in this INDEX


def test_load_project_context(tmp_path):
    md = tmp_path / "context.md"
    md.write_text(
        "# Project Context\n\n"
        "## Surgical timeline\n2024-06: cholecystectomy.\n2024-08: post-op rash (open).\n\n"
        "## Checklist\nBile-acid: rs2287622, rs56163822.\n",
        encoding="utf-8",
    )
    ctx = rebuild.load_project_context(md)
    assert "cholecystectomy" in ctx["timeline"]
    assert ctx["checklist_rsids"] == ["rs2287622", "rs56163822"]
    assert "Checklist" in ctx["sections"]


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_rendered_output_is_byte_deterministic(tmp_path):
    d, m = write_specs(tmp_path)
    o1, o2 = tmp_path / "o1", tmp_path / "o2"
    rebuild.write_document(d, m, o1, o1 / "archive")
    rebuild.write_document(d, m, o2, o2 / "archive")
    for name in ("Pharmacogenomics Analysis.md", "Pharmacogenomics Analysis.html"):
        assert (o1 / name).read_bytes() == (o2 / name).read_bytes(), name
