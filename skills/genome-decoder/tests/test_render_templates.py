"""Tests for the HelixyAI report renderer (Workstream D2/D3).

All fixtures are synthetic — fabricated subject, rsIDs, genes, citations.
"""

from datetime import date

import pytest

import _common as C
import report_render as R


# --------------------------------------------------------------------------- #
# Synthetic fixtures
# --------------------------------------------------------------------------- #


def _prov(doc_id="04_Sample_Pharmacogenomics"):
    return C.ProvenanceBlock(
        doc_id=doc_id,
        produced_by="claude-opus-4-8[1m]",
        produced_on=date(2026, 1, 15),
        phase=3,
        source_genome_path="/data/sample_genome.txt",
        source_genome_sha256="0000000000000000",
        source_genome_assembly="GRCh37",
        source_genome_line_count_verified=100000,
        genotype_index_path="/data/sample/INDEX_genotype_truth.tsv",
        genotype_index_sha256="1111111111111111",
        removed_claims_count=0,
        added_claims_count=2,
        external_sources_used=("CPIC", "dbSNP"),
        external_sources_access_date=date(2026, 1, 15),
        supersedes="/data/sample/archive/v1/04_Sample_Pharmacogenomics.md",
        supersedes_sha256="2222222222222222",
    )


def _cpic(label="CPIC GENE1 Guideline"):
    return C.Citation(source_key="cpic", label=label, url="https://cpicpgx.org/guidelines/",
                      access_date="2026-01-15")


def _dbsnp(rsid="rs0000001"):
    return C.Citation(source_key="dbsnp", label=f"dbSNP {rsid}",
                      url=f"https://www.ncbi.nlm.nih.gov/snp/{rsid}", access_date="2026-01-15")


def _finding(tier=1, implication="carries one reduced-function allele, predicting intermediate enzyme activity per the CPIC guideline.",
             hist=""):
    return C.Finding(
        gene="GENE1", name="Reduced Metabolizer", tier=tier, evidence="CPIC Level A",
        triples=(C.Triple("rs0000001", "7", "1000000", "AG"),),
        implication=implication, citations=(_cpic(), _dbsnp()),
        subtitle="Cytochrome P450 family", historical_note=hist,
    )


def _report_doc(findings=None, alert=True, hist=""):
    findings = findings if findings is not None else (_finding(hist=hist),
                                                      _finding(tier=2, implication="reference genotype predicting normal function."),)
    alert_rows = ()
    if alert:
        alert_rows = (C.AlertRow(
            drug="ExampleDrug A", gene_genotype="GENE1 *2/*2 (rs0000001 AG)",
            evidence="CPIC Level A",
            recommendation="Reduced-function — consider an alternative agent; consult your prescribing clinician.",
            citation=_cpic()),)
    return C.ReportDocument(
        doc_id="04_Sample_Pharmacogenomics", title="Pharmacogenomics Analysis",
        group="Pharmacology", provenance=_prov(),
        kicker="Pharmacology · Document 04 of 24",
        subtitle="How the subject's genotype is predicted to influence medication response.",
        facts=("2 findings", "1 Tier 1"),
        alert_rows=alert_rows, findings=tuple(findings),
        genotype_rows=(C.GenotypeRow(C.Triple("rs0000001", "7", "1000000", "AG"), "GENE1", 1),),
    )


def _manifest():
    docs = (
        C.ReportDoc("01_Sample_Exec", "Executive Summary", "Executive Summary.html", "Overview",
                    "01", blurb="Top findings.", tier_summary="2 Tier 1", tier=1,
                    findings_label="12 findings", available=True,
                    search_terms="executive summary overview", icon_token="SUMMARY"),
        C.ReportDoc("04_Sample_Pharmacogenomics", "Pharmacogenomics Analysis",
                    "Pharmacogenomics Analysis.html", "Pharmacology", "04",
                    blurb="Genotype-guided medication response.", tier_summary="1 Tier 1",
                    tier=1, findings_label="2 findings", available=True,
                    search_terms="pharmacogenomics drug cpic", icon_token="PILL"),
        C.ReportDoc("06_Sample_Caffeine", "Caffeine Metabolism", "index.html", "Pharmacology",
                    "06", blurb="Caffeine clearance.", tier_summary="1 Tier 2", tier=2,
                    available=False, search_terms="caffeine cyp1a2", icon_token="DROP"),
    )
    return C.ReportManifest(
        subject_label="Sample Subject", report_id="HX-2026-0042", assembly="GRCh37",
        array="consumer SNP · v5", access_date="2026-01-15",
        sources=("CPIC", "dbSNP"), source_sha256="0000000000000000",
        supersedes="prior v1", supersedes_sha256="1111111111111111",
        docs=docs, groups=("Overview", "Pharmacology"),
        stats={"documents": 3, "variants_reviewed": 42, "tier1": 2, "cpic_a": 1, "carriers": 0},
        build_label="genome-decoder",
    )


# --------------------------------------------------------------------------- #
# Seams
# --------------------------------------------------------------------------- #


def test_templates_have_all_seams():
    doc = R._load_template("document.html")
    for name in ("TITLE", "META", "SIDEBAR", "ARTICLE"):
        assert f"<!-- HELIXY:{name}:START -->" in doc and f"<!-- HELIXY:{name}:END -->" in doc
    idx = R._load_template("index.html")
    for name in ("TITLE", "META", "STATS", "SUBJECT", "PROVENANCE", "HIGHLIGHTS", "GRID"):
        assert f"<!-- HELIXY:{name}:START -->" in idx and f"<!-- HELIXY:{name}:END -->" in idx


def test_replace_seam_roundtrip_and_missing():
    src = "<!-- HELIXY:X:START -->\nold\n<!-- HELIXY:X:END -->"
    out = R._replace_seam(src, "X", "new")
    assert "new" in out and "old" not in out
    with pytest.raises(C.DecoderError):
        R._replace_seam("no seam here", "X", "new")


# --------------------------------------------------------------------------- #
# Document rendering
# --------------------------------------------------------------------------- #


def test_document_html_self_contained_and_contract():
    html = R.render_document_html(_report_doc(), _manifest())
    # self-contained: no external script/style/font loads (citation <a href> ok)
    assert "<script src=" not in html
    assert "stylesheet" not in html
    for bad in ("googleapis", "cdn.", "unpkg", "jsdelivr"):
        assert bad not in html
    # SPEC HTML contract
    assert 'data-rsid="rs0000001"' in html and 'data-genotype="AG"' in html
    assert 'data-chrom="7"' in html and 'data-pos="1000000"' in html
    assert '<meta name="provenance:source_sha256" content="0000000000000000">' in html
    assert 'rel="external" data-access-date="2026-01-15"' in html
    # design components
    assert 'class="finding t1"' in html and 'class="tier t1"' in html
    assert 'class="alert-tbl"' in html and 'class="gt"' in html
    assert "Consult your prescribing clinician." in html
    # nav reflects manifest
    assert "Pharmacogenomics Analysis" in html  # breadcrumb current
    assert 'href="Executive Summary.html"' in html  # sidebar cross-link
    assert 'class="pager"' in html


def test_document_render_deterministic():
    rd, man = _report_doc(), _manifest()
    assert R.render_document_html(rd, man) == R.render_document_html(rd, man)


def test_index_html_injects_manifest():
    html = R.render_index_html(_manifest())
    assert "<title>HelixyAI — Genome Report · Sample Subject</title>" in html
    assert '<meta name="provenance:documents" content="3">' in html
    # one card per ReportDoc + cross-links + icon placeholders preserved for JS
    assert html.count('class="card') == 3
    assert 'href="Pharmacogenomics Analysis.html"' in html
    assert "${ICON_PILL}" in html and "${ICON_SUMMARY}" in html
    # group counts
    assert "Pharmacology <span class=\"gn\">2 docs</span>" in html
    # stats / highlights / subject injected
    assert '<div class="n">42</div>' in html  # variants reviewed stat
    assert "Sample Subject" in html


def test_index_render_deterministic():
    man = _manifest()
    assert R.render_index_html(man) == R.render_index_html(man)


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #


def test_write_blocks_aspirational_finding(tmp_path):
    bad = _report_doc(findings=(_finding(implication="this variant may benefit the subject."),))
    with pytest.raises(C.AspirationalClaimDetected):
        R.write_report_document(bad, _manifest(), out_dir=tmp_path, archive_dir=tmp_path / "archive")


def test_write_allows_archive_quoted_historical_note(tmp_path):
    rd = _report_doc(hist="Prior analysis flagged this region and may have overstated the effect; superseded.")
    written = R.write_report_document(rd, _manifest(), out_dir=tmp_path, archive_dir=tmp_path / "archive")
    assert (tmp_path / "Pharmacogenomics Analysis.html").exists()
    assert written["markdown"].endswith(".md")
    md = (tmp_path / "Pharmacogenomics Analysis.md").read_text(encoding="utf-8")
    assert "## Provenance Summary" in md
    assert "[verbatim from archive" in md


def test_write_index(tmp_path):
    written = R.write_report_index(_manifest(), out_dir=tmp_path)
    assert (tmp_path / "index.html").exists()
    assert "HelixyAI" in (tmp_path / "index.html").read_text(encoding="utf-8")


def test_citation_offlist_rejected():
    with pytest.raises(C.AllowlistError):
        C.Citation(source_key="snpedia", label="x", url="https://snpedia.com/", access_date="2026-01-15")


def test_finding_requires_triple_and_citation():
    with pytest.raises(C.DecoderError):
        C.Finding(gene="G", name="n", tier=1, evidence="CPIC Level A", triples=(),
                  implication="x", citations=(_cpic(),))
    with pytest.raises(C.DecoderError):
        C.Finding(gene="G", name="n", tier=1, evidence="CPIC Level A",
                  triples=(C.Triple("rs1", "1", "2", "AA"),), implication="x", citations=())
