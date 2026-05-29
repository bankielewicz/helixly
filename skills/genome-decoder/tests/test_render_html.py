"""Regression tests for the markdown→HTML renderer (render._md_blocks_to_html).

Audit finding 2 (2026-05-28): a line starting with a block-prefix character that
matched no block branch (``#`` not followed by whitespace, a stray ``|`` that is
not a table, ``***``) advanced no branch and the paragraph loop refused to
consume it, hanging the renderer. The loop-progress guard fixes this. These
tests would hang on the unpatched code, so they double as the regression.
"""

import render


def _html(md: str) -> str:
    return render._md_blocks_to_html(md, access_date="2026-05-28")


def test_hash_without_space_does_not_hang():
    out = _html("#nospace heading-like line\n")
    assert "nospace" in out


def test_stray_pipe_line_does_not_hang():
    out = _html("| a stray pipe line that is not a table\n")
    assert "stray pipe" in out


def test_triple_asterisk_does_not_hang():
    out = _html("***\n")
    assert out is not None  # completed without hanging


def test_normal_constructs_still_render():
    md = (
        "## Heading\n"
        "\n"
        "A paragraph with a `rs1801133` code span.\n"
        "\n"
        "| rsid | genotype |\n"
        "| --- | --- |\n"
        "| rs1801133 | AG |\n"
        "\n"
        "- bullet one\n"
        "- bullet two\n"
    )
    out = _html(md)
    assert "<h2>" in out
    assert "<table>" in out and "<th>" in out
    assert "<ul>" in out and "<li>" in out
    assert 'data-rsid="rs1801133"' in out
