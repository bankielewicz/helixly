"""Regression tests for the aspirational-phrase blacklist gate (SPEC Rule 1).

Audit finding 1 (2026-05-28): the archive-attributed-quote exemption only
exempted the single line carrying the ``[verbatim from archive]`` marker, so the
continuation lines of a multi-line attributed blockquote — the pattern Karen's
Phase 5/7 reference docs relied on — were flagged and the write gate refused to
write the document. These tests pin the corrected behaviour.
"""

import _common


def test_multiline_archive_blockquote_is_exempt():
    """A multi-line attributed blockquote is exempt on every line (the fix)."""
    text = (
        "## Crohn's Disease Monitoring Protocol\n"
        "\n"
        "> [verbatim from archive: 21_Medical_Notes.md lines 124-129]\n"
        "> This variant may benefit from monitoring and could increase risk\n"
        "> roughly twofold; clinicians should consider screening as needed.\n"
    )
    assert _common.find_blacklist_hits(text) == []


def test_marker_not_required_on_first_blockquote_line():
    """Exemption holds wherever in the run the marker sits (order-independent)."""
    text = (
        "> The prior analysis said risk may be elevated and could vary.\n"
        "> [verbatim from archive: 18_Comprehensive_Genome_Analysis.md]\n"
    )
    assert _common.find_blacklist_hits(text) == []


def test_single_line_removed_claim_bullet_is_exempt():
    """The Provenance Summary 'Removed claims' bullet quotes v1 text inline."""
    text = (
        "**Removed claims** (verbatim quote → reason removed):\n"
        '- "may benefit from gluten avoidance" [verbatim from archive: 07_Nutrition_Analysis.md] '
        "→ reason: aspirational phrasing\n"
    )
    assert _common.find_blacklist_hits(text) == []


def test_real_aspirational_text_is_still_flagged():
    """A normal sentence with hedging — no archive attribution — must flag."""
    text = "This variant may benefit the subject and should consider supplementation.\n"
    tokens = {h.token.lower() for h in _common.find_blacklist_hits(text)}
    assert "may" in tokens
    assert "should consider" in tokens


def test_aspirational_after_blockquote_ends_is_flagged():
    """Once the attributed blockquote ends, normal scanning resumes."""
    text = (
        "> [verbatim from archive: x.md]\n"
        "> historical text that may hedge\n"
        "\n"
        "Current analysis: the subject may respond well.\n"  # NOT in the quote
    )
    hits = _common.find_blacklist_hits(text)
    assert [h.lineno for h in hits] == [4]


def test_non_attributed_blockquote_is_still_scanned():
    """A blockquote WITHOUT an archive attribution is not exempt."""
    text = "> editorial aside: results may vary\n"
    tokens = {h.token.lower() for h in _common.find_blacklist_hits(text)}
    assert "may" in tokens


def test_inline_code_and_fenced_code_remain_exempt():
    """Pre-existing exemptions are unaffected by the fix."""
    inline = "The blacklist token `may` is cited here as data, not used.\n"
    assert _common.find_blacklist_hits(inline) == []
    fenced = "```\nGrep pattern: may|might|could\n```\n"
    assert _common.find_blacklist_hits(fenced) == []


def test_write_doc_writes_a_doc_with_a_multiline_archive_quote(tmp_path):
    """End-to-end: a Document whose body carries a multi-line attributed quote
    now writes instead of raising AspirationalClaimDetected."""
    import render
    from datetime import date
    from _common import Document, ProvenanceBlock, Section

    prov = ProvenanceBlock(
        doc_id="21_Medical_Notes",
        produced_by="claude-opus-4-8[1m]",
        produced_on=date(2026, 5, 28),
        phase=5,
        source_genome_path="C:/Projects/Health/karen/genome.txt",
        source_genome_sha256="60cc802d",
        source_genome_assembly="GRCh37",
        source_genome_line_count_verified=632035,
        genotype_index_path="C:/Projects/Health/karen/claude.ai-docs/INDEX_genotype_truth.tsv",
        genotype_index_sha256="a149de3a",
        removed_claims_count=0,
        added_claims_count=0,
        external_sources_used=("dbSNP",),
        external_sources_access_date=date(2026, 5, 28),
        supersedes="C:/Projects/Health/karen/claude.ai-docs/archive/v1_sonnet46/21_Medical_Notes.md",
        supersedes_sha256="deadbeef",
    )
    body = (
        "> [verbatim from archive: 21_Medical_Notes.md lines 124-129]\n"
        "> Crohn's carriers may face roughly twofold risk; clinicians should consider screening.\n"
    )
    doc = Document(
        path=tmp_path / "21_Medical_Notes.md",
        provenance=prov,
        title="Medical Notes",
        sections=(Section(heading="Crohn's Disease Monitoring Protocol", body_md=body),),
    )
    written = render.write_doc(doc, archive_dir=tmp_path / "archive", also_html=True)
    assert (tmp_path / "21_Medical_Notes.md").exists()
    assert "verbatim from archive" in (tmp_path / "21_Medical_Notes.md").read_text(encoding="utf-8")
    assert written["html"].endswith(".html")
