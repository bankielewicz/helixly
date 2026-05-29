"""Tests for index_build.py (Phase 0 INDEX) — substrate fully mocked.

The genome-reader substrate is never invoked: ``_common.run_substrate`` is
monkeypatched with a dispatcher that returns synthetic ``identify`` /
``summarize`` dicts and a synthetic ``lookup`` TSV. Every rsID, genotype, and
archive filename here is synthetic — no real subject, no real genome.
"""

import _common
import index_build
import pytest

# Synthetic 4-column lookup TSV (the contract genome-reader's
# ``lookup.py --columns rsid,chrom,pos,genotype`` emits):
#   rs0000001 — called (found=y)
#   rs0000002 — present but no-call '--' (found=n)
#   rs0000003 — not on the chip (found=n)
LOOKUP_TSV = (
    "rsid\tchrom\tpos\tgenotype\n"
    "rs0000001\t1\t11111\tAG\n"
    "rs0000002\t2\t22222\t--\n"
    "rs0000003\t\t\tnot_tested\n"
)


def make_substrate(lookup_tsv=LOOKUP_TSV, *, build="GRCh37", fmt="consumer_dna:23andme",
                   snp_count=42, no_call_rate=0.02):
    """A run_substrate stand-in that dispatches on the script name + json_out."""

    def _side_effect(script, *args, json_out=False):
        if script == "identify.py":
            return {"format": fmt, "size_bytes": 123, "compressed": False}
        if script == "summarize.py":
            return {
                "format": fmt,
                "snp_count": snp_count,
                "build": build,
                "no_call_rate": no_call_rate,
                "chromosome_distribution": {},
            }
        if script == "lookup.py":
            return lookup_tsv
        raise AssertionError(f"unexpected substrate script: {script!r}")

    return _side_effect


def write_archive(tmp_path):
    """A synthetic 2-doc archive. Pool order (docs sorted, rsIDs first-seen):
    rs0000001, rs0000002, rs0000003.
    """
    arch = tmp_path / "archive"
    arch.mkdir()
    (arch / "doc_a.md").write_text(
        "MTHFR analysis cites rs0000001 and rs0000002.\n", encoding="utf-8"
    )
    (arch / "doc_b.md").write_text(
        "Re-mentions rs0000002; also rs0000003 (not on chip).\n", encoding="utf-8"
    )
    return arch


def make_genome(tmp_path):
    g = tmp_path / "synthetic_export.txt"
    g.write_text("# synthetic consumer DNA placeholder\n", encoding="utf-8")
    return g


def read_index_rows(out_dir):
    text = (out_dir / index_build.INDEX_TSV).read_text(encoding="utf-8")
    lines = text.splitlines()
    return lines[0].split("\t"), [ln.split("\t") for ln in lines[1:]]


def test_index_has_exact_seven_columns_and_correct_values(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "run_substrate", make_substrate())
    arch = write_archive(tmp_path)
    genome = make_genome(tmp_path)
    out = tmp_path / "out"

    index_build.build_index(genome, arch, out)
    header, rows = read_index_rows(out)

    assert header == list(index_build.INDEX_COLUMNS)
    assert len(header) == 7
    assert rows == [
        ["rs0000001", "1", "11111", "AG", "y", "doc_a.md", "0"],
        ["rs0000002", "2", "22222", "--", "n", "doc_a.md,doc_b.md", "0"],
        ["rs0000003", "", "", "not_tested", "n", "doc_b.md", "0"],
    ]


def test_every_row_is_discovered_in_phase_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "run_substrate", make_substrate())
    out = tmp_path / "out"
    index_build.build_index(make_genome(tmp_path), write_archive(tmp_path), out)
    _, rows = read_index_rows(out)
    assert all(r[-1] == "0" for r in rows)


def test_summary_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "run_substrate", make_substrate())
    out = tmp_path / "out"
    summary = index_build.build_index(make_genome(tmp_path), write_archive(tmp_path), out)
    assert summary["rsids_total"] == 3
    assert summary["rsids_found"] == 1
    assert summary["rsids_not_found"] == 2
    assert summary["assembly"] == "GRCh37"
    # The INDEX SHA is reported, never written into the file it hashes.
    assert _common.sha256_file(out / index_build.INDEX_TSV) == summary["index_sha256"]
    assert summary["index_sha256"] not in (out / index_build.INDEX_TSV).read_text(encoding="utf-8")


def test_build_null_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "run_substrate", make_substrate(build=None))
    with pytest.raises(_common.SubstrateError, match="build=null"):
        index_build.build_index(make_genome(tmp_path), write_archive(tmp_path), tmp_path / "out")


def test_non_consumer_format_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "run_substrate", make_substrate(fmt="vcf"))
    with pytest.raises(_common.SubstrateError, match="consumer_dna"):
        index_build.build_index(make_genome(tmp_path), write_archive(tmp_path), tmp_path / "out")


def test_lookup_header_mismatch_raises(tmp_path, monkeypatch):
    bad = "rsid\tgenotype\nrs0000001\tAG\n"  # missing chrom/pos — old default shape
    monkeypatch.setattr(_common, "run_substrate", make_substrate(lookup_tsv=bad))
    with pytest.raises(_common.SubstrateError, match="header"):
        index_build.build_index(make_genome(tmp_path), write_archive(tmp_path), tmp_path / "out")


def test_outputs_are_byte_deterministic(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "run_substrate", make_substrate())
    arch = write_archive(tmp_path)
    genome = make_genome(tmp_path)
    out1, out2 = tmp_path / "out1", tmp_path / "out2"

    index_build.build_index(genome, arch, out1)
    index_build.build_index(genome, arch, out2)

    for name in (index_build.INDEX_TSV, index_build.INDEX_MD):
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes(), name


def test_companion_lists_only_gap_rsids(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "run_substrate", make_substrate())
    out = tmp_path / "out"
    index_build.build_index(make_genome(tmp_path), write_archive(tmp_path), out)
    md = (out / index_build.INDEX_MD).read_text(encoding="utf-8")
    assert "## Chip coverage gaps (found = n)" in md
    assert "rs0000002" in md and "rs0000003" in md
    # the found rsID appears nowhere in the gap companion
    assert "rs0000001" not in md
    assert "no wall-clock" not in md  # sanity: companion carries no date line
