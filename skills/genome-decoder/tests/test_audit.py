"""Tests for audit.py (Phase 1 read-only audit).

No substrate and no network — audit reads archive markdown + a hand-written
INDEX TSV. Every rsID, genotype, gene, and filename here is synthetic.
"""

import _common as C
import audit


def write_index(tmp_path, rows):
    """rows: iterable of (rsid, chrom, pos, genotype, found)."""
    p = tmp_path / "INDEX_genotype_truth.tsv"
    header = "rsid\tchromosome\tposition\tgenotype\tfound\tsource_docs\tdiscovered_in_phase"
    lines = [header] + ["\t".join([r, c, pos, gt, f, "doc.md", "0"]) for r, c, pos, gt, f in rows]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def write_doc(archive, name, body):
    (archive / name).write_text(body, encoding="utf-8")


def make_archive(tmp_path):
    arch = tmp_path / "archive"
    arch.mkdir()
    write_doc(arch, "doc_a_keep.md",
              "# Doc A\nGENE1 metabolizer status rs0000001 AG per CPIC guideline.\n")
    write_doc(arch, "doc_b_rewrite.md",
              "# Doc B\nrs0000001 AG predicts intermediate enzyme activity.\n")
    write_doc(arch, "doc_c_delete.md",
              "# Doc C\n"
              "This variant may benefit your methylation.\n"
              "rs0000002 confers deficiency risk.\n"
              "rs0000009 allele increases carrier status.\n")
    return arch


def standard_index(tmp_path):
    return write_index(tmp_path, [
        ("rs0000001", "1", "100", "AG", "y"),   # supporting
        ("rs0000002", "2", "200", "--", "n"),   # found=n -> not supporting
        # rs0000009 intentionally absent from the INDEX
    ])


def claims_of(findings, doc):
    return next(d["claims"] for d in findings["docs"] if d["doc"] == doc)


def only(claims):
    assert len(claims) == 1, claims
    return claims[0]


# --------------------------------------------------------------------------- #
# Dispositions across the 3-doc archive
# --------------------------------------------------------------------------- #


def test_summary_counts(tmp_path):
    out = tmp_path / "out"
    findings = audit.run_audit(make_archive(tmp_path), standard_index(tmp_path), out)
    s = findings["summary"]
    assert s["docs"] == 3
    assert s["claims"] == 5
    assert s["dispositions"] == {"delete": 3, "rewrite-with-citation": 1, "keep": 1}
    # output files exist
    assert (out / audit.FINDINGS_JSON).exists() and (out / audit.CLAIMS_TSV).exists()


def test_keep_claim(tmp_path):
    findings = audit.run_audit(make_archive(tmp_path), standard_index(tmp_path), tmp_path / "out")
    c = only(claims_of(findings, "doc_a_keep.md"))
    assert c["disposition"] == "keep"
    assert c["has_citation"] is True
    assert c["supporting_rsids"] == ["rs0000001"]
    assert c["blacklist_tokens"] == []


def test_rewrite_claim(tmp_path):
    findings = audit.run_audit(make_archive(tmp_path), standard_index(tmp_path), tmp_path / "out")
    c = only(claims_of(findings, "doc_b_rewrite.md"))
    assert c["disposition"] == "rewrite-with-citation"
    assert c["has_citation"] is False
    assert c["supporting_rsids"] == ["rs0000001"]
    assert c["missing_citation"] is True


def test_delete_claims_blacklist_foundn_and_absent(tmp_path):
    findings = audit.run_audit(make_archive(tmp_path), standard_index(tmp_path), tmp_path / "out")
    claims = {c["text"]: c for c in claims_of(findings, "doc_c_delete.md")}
    assert all(c["disposition"] == "delete" for c in claims.values())
    # (3) aspirational
    bl = next(c for c in claims.values() if c["blacklist_tokens"])
    assert "may" in bl["blacklist_tokens"]
    # found=n rsID gives no support -> delete (the found=y decision)
    foundn = next(c for c in claims.values() if c["rsids"] == ["rs0000002"])
    assert foundn["supporting_rsids"] == [] and foundn["missing_rsid_linkage"] is True
    # (4) rsID absent from INDEX
    absent = next(c for c in claims.values() if c["rsids"] == ["rs0000009"])
    assert absent["rsids_absent_from_index"] == ["rs0000009"]


def test_blacklist_only_line_is_captured_even_without_clinical_content(tmp_path):
    arch = tmp_path / "archive"
    arch.mkdir()
    write_doc(arch, "d.md", "# D\nIt may help.\n")
    findings = audit.run_audit(arch, standard_index(tmp_path), tmp_path / "out")
    c = only(claims_of(findings, "d.md"))
    assert c["clinical"] is False
    assert c["blacklist_tokens"] == ["may"]
    assert c["disposition"] == "delete"


# --------------------------------------------------------------------------- #
# Subsections 5, 8, 7, 2
# --------------------------------------------------------------------------- #


def test_genotype_mismatch_vs_index(tmp_path):
    arch = tmp_path / "archive"
    arch.mkdir()
    write_doc(arch, "d.md", "# D\nrs0000001 GG indicates poor metabolism.\n")
    findings = audit.run_audit(arch, standard_index(tmp_path), tmp_path / "out")
    c = only(claims_of(findings, "d.md"))
    assert c["stated_genotype"] == "GG"
    assert c["genotype_mismatch"] is True
    # advisory only — disposition still follows the locked rule (supporting, no citation)
    assert c["disposition"] == "rewrite-with-citation"


def test_internal_contradiction_across_docs(tmp_path):
    arch = tmp_path / "archive"
    arch.mkdir()
    write_doc(arch, "d1.md", "# 1\nrs0000001 AG reduces enzyme activity.\n")
    write_doc(arch, "d2.md", "# 2\nrs0000001 GG reduces enzyme activity.\n")
    findings = audit.run_audit(arch, standard_index(tmp_path), tmp_path / "out")
    contras = findings["contradictions"]
    assert len(contras) == 1
    assert contras[0]["rsid"] == "rs0000001"
    assert sorted(contras[0]["genotypes"]) == ["AG", "GG"]


def test_project_terms_flagged_when_supplied(tmp_path):
    arch = tmp_path / "archive"
    arch.mkdir()
    write_doc(arch, "d.md", "# D\nGluten sensitivity is noted in the history.\n")
    findings = audit.run_audit(arch, standard_index(tmp_path), tmp_path / "out",
                               project_terms_arg="gluten")
    c = only(claims_of(findings, "d.md"))
    assert c["project_terms"] == ["gluten"]
    assert findings["project_terms"] == ["gluten"]


def test_project_terms_empty_without_flag(tmp_path):
    arch = tmp_path / "archive"
    arch.mkdir()
    write_doc(arch, "d.md", "# D\nGluten sensitivity is noted in the history.\n")
    findings = audit.run_audit(arch, standard_index(tmp_path), tmp_path / "out")
    assert findings["project_terms"] == []
    assert only(claims_of(findings, "d.md"))["project_terms"] == []


def test_citation_marker_detection(tmp_path):
    arch = tmp_path / "archive"
    arch.mkdir()
    write_doc(arch, "d.md",
              "# D\nrs0000001 AG reduced function (PMID: 12345).\nrs0000001 AG reduced function.\n")
    findings = audit.run_audit(arch, standard_index(tmp_path), tmp_path / "out")
    claims = claims_of(findings, "d.md")
    cited = next(c for c in claims if "PMID" in c["text"])
    uncited = next(c for c in claims if "PMID" not in c["text"])
    assert cited["has_citation"] is True and cited["disposition"] == "keep"
    assert uncited["has_citation"] is False and uncited["disposition"] == "rewrite-with-citation"


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_outputs_are_byte_deterministic(tmp_path):
    arch = make_archive(tmp_path)
    index = standard_index(tmp_path)
    out1, out2 = tmp_path / "o1", tmp_path / "o2"
    audit.run_audit(arch, index, out1)
    audit.run_audit(arch, index, out2)
    for name in (audit.FINDINGS_JSON, audit.CLAIMS_TSV):
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes(), name
