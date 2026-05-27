"""Regression tests for fetch_assets.py — timeout, partial-file cleanup,
manifest parsing, and chip-union build (#6, #8)."""

from __future__ import annotations

import gzip
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_assets  # noqa: E402


# --------------------------------------------------------------------------
# #8 — timeout + .part cleanup. Tests exercise _stream_dbsnp_filtered, which
# is the streaming path that was previously _download_and_filter. Behavior
# preserved across the #6 rework.
# --------------------------------------------------------------------------


def test_urlopen_receives_timeout(monkeypatch, tmp_path):
    """Regression for #8: urlopen is called with an explicit timeout argument."""
    captured: dict = {}

    def fake_urlopen(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        raise RuntimeError("stop after capture")

    monkeypatch.setattr(fetch_assets.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError):
        fetch_assets._stream_dbsnp_filtered(
            "http://example.invalid/x",
            {"rs1"},
            tmp_path / "out.tsv.gz",
            timeout=30,
        )
    assert captured.get("timeout") == 30, captured


def test_env_var_overrides_timeout(monkeypatch):
    """Regression for #8: HELIXLY_FETCH_TIMEOUT overrides the default."""
    monkeypatch.setenv("HELIXLY_FETCH_TIMEOUT", "7")
    assert fetch_assets._timeout_seconds() == 7.0


def test_partial_file_removed_on_failure(monkeypatch, tmp_path):
    """Regression for #8: .part file is removed when urlopen raises."""
    def fake_urlopen(url, timeout=None):
        raise OSError("simulated network failure")

    monkeypatch.setattr(fetch_assets.urllib.request, "urlopen", fake_urlopen)
    out_path = tmp_path / "out.tsv.gz"
    part = out_path.with_suffix(out_path.suffix + ".part")
    with pytest.raises(OSError):
        fetch_assets._stream_dbsnp_filtered(
            "http://example.invalid/x", {"rs1"}, out_path, timeout=30,
        )
    assert not part.exists(), f".part file leaked at {part}"


def test_existing_part_file_removed_on_failure(monkeypatch, tmp_path):
    """Regression for #8: a pre-existing .part file is removed on failure.

    Pre-creating the .part file forces the finally clause to actually run
    unlink(); without pre-creation, the failure path never creates a file
    to clean up and the assertion would pass trivially.
    """
    def fake_urlopen(url, timeout=None):
        raise OSError("simulated mid-stream failure")

    monkeypatch.setattr(fetch_assets.urllib.request, "urlopen", fake_urlopen)
    out_path = tmp_path / "out.tsv.gz"
    part = out_path.with_suffix(out_path.suffix + ".part")
    part.write_bytes(b"stale partial data")
    assert part.exists()
    with pytest.raises(OSError):
        fetch_assets._stream_dbsnp_filtered(
            "http://example.invalid/x", {"rs1"}, out_path, timeout=30,
        )
    assert not part.exists(), f".part file leaked at {part}"
    assert not out_path.exists(), f"out file leaked at {out_path}"


# --------------------------------------------------------------------------
# #6 — Illumina manifest parsing and chip-union build.
# --------------------------------------------------------------------------


_MANIFEST_CSV = """\
Illumina, Inc.
[Header]
Descriptor File Name,fake-manifest.csv
Date Manufactured,2018-01-01
[Assay]
IlmnID,Name,SourceSeq,GenomeBuild,Chr,MapInfo
1:100:A:G,rs1,ACGT,37,1,100
2:200:C:T,rs2,ACGT,37,2,200
3:300:A:T,internal_id_3,ACGT,37,3,300
4:400:G:C,rs4,ACGT,37,4,400
5:500:T:A,i777,ACGT,37,5,500
[Controls]
something,else
"""


def test_extract_rsids_skips_non_rs_names():
    """Regression for #6: only rsIDs are extracted; internal Illumina IDs are dropped."""
    rsids = fetch_assets._extract_rsids_from_manifest_csv(_MANIFEST_CSV)
    assert rsids == {"rs1", "rs2", "rs4"}


def test_extract_rsids_handles_section_boundary():
    """Regression for #6: rows after [Controls] are not parsed."""
    csv_with_extra = _MANIFEST_CSV + "rs_bogus_should_not_appear,ACGT,37,9,9\n"
    rsids = fetch_assets._extract_rsids_from_manifest_csv(csv_with_extra)
    assert "rs_bogus_should_not_appear" not in rsids


def test_fetch_manifest_rsids_zip(monkeypatch):
    """Regression for #6: zipped manifest payload is unpacked, CSV inside is parsed."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("nested/inner.csv", _MANIFEST_CSV)
    zip_bytes = buf.getvalue()

    class FakeResp:
        def __init__(self, b): self._b = b
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self._b

    monkeypatch.setattr(
        fetch_assets.urllib.request, "urlopen",
        lambda url, timeout=None: FakeResp(zip_bytes),
    )
    rsids = fetch_assets._fetch_manifest_rsids("gsa_v1", timeout=30)
    assert rsids == {"rs1", "rs2", "rs4"}


def test_fetch_manifest_rsids_csv(monkeypatch):
    """Regression for #6: raw CSV manifest payload is parsed without unzip."""
    csv_bytes = _MANIFEST_CSV.encode("utf-8")

    class FakeResp:
        def __init__(self, b): self._b = b
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self._b

    monkeypatch.setattr(
        fetch_assets.urllib.request, "urlopen",
        lambda url, timeout=None: FakeResp(csv_bytes),
    )
    rsids = fetch_assets._fetch_manifest_rsids("omniexpress_v1_1", timeout=30)
    assert rsids == {"rs1", "rs2", "rs4"}


def test_fetch_manifest_rsids_zero_rsids_raises(monkeypatch):
    """Regression for #6: zero-rsID payload signals a column-layout change.

    Without this assert, a silent change to Illumina's CSV format (e.g. renaming
    'Name' to 'Locus Name') would yield an empty rsID set and a useless output.
    """
    empty_csv = "[Header]\nfoo,bar\n[Assay]\nIlmnID,SourceSeq\n1,ACGT\n[Controls]\n"

    class FakeResp:
        def __init__(self, b): self._b = b
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self._b

    monkeypatch.setattr(
        fetch_assets.urllib.request, "urlopen",
        lambda url, timeout=None: FakeResp(empty_csv.encode()),
    )
    with pytest.raises(RuntimeError, match="zero rsIDs"):
        fetch_assets._fetch_manifest_rsids("omniexpress_v1_1", timeout=30)


def test_stream_dbsnp_filters_to_rsid_set(monkeypatch, tmp_path):
    """Regression for #6: dbSNP rows are kept iff the rsID is in the chip union."""
    # Synthetic dbSNP VCF: header lines + 5 records, two of which match the chip set.
    vcf = b"""\
##fileformat=VCFv4.2
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
1\t100\trs1\tA\tG\t.\tPASS\t.
2\t200\trs2\tC\tT\t.\tPASS\t.
3\t300\trs_not_on_chip\tA\tT\t.\tPASS\t.
4\t400\trs4\tG\tC,T\t.\tPASS\t.
5\t500\trs_indel\tACGT\tA\t.\tPASS\t.
"""
    gz_bytes = io.BytesIO()
    with gzip.open(gz_bytes, "wb") as gz:
        gz.write(vcf)
    body = gz_bytes.getvalue()

    class FakeResp:
        def __init__(self, b): self._b = io.BytesIO(b)
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=-1): return self._b.read(n)
        def readable(self): return True

    monkeypatch.setattr(
        fetch_assets.urllib.request, "urlopen",
        lambda url, timeout=None: FakeResp(body),
    )
    out_path = tmp_path / "rsid_grch37.full.tsv.gz"
    rsid_set = {"rs1", "rs2", "rs4", "rs_indel"}
    written = fetch_assets._stream_dbsnp_filtered(
        "http://example.invalid/dbsnp.vcf.gz",
        rsid_set, out_path, timeout=30,
    )
    # rs1 + rs2 + rs4 kept; rs_indel skipped (ref length > 1); rs_not_on_chip skipped (not in set).
    assert written == 3
    with gzip.open(out_path, "rt") as fh:
        rows = [ln.rstrip("\n").split("\t") for ln in fh if not ln.startswith("#")]
    keep = {r[0] for r in rows}
    assert keep == {"rs1", "rs2", "rs4"}
    # rs4 has multi-allelic alt; only the first alt is kept.
    rs4 = next(r for r in rows if r[0] == "rs4")
    assert rs4 == ["rs4", "4", "400", "G", "C"]


def test_build_chip_union_end_to_end(monkeypatch, tmp_path):
    """Regression for #6: orchestrator fetches both manifests + dbSNP and writes the join."""
    # Manifest 1 (GSA, zip): contains rs1, rs2.
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as zf:
        zf.writestr("inner.csv", """\
[Header]
foo,bar
[Assay]
IlmnID,Name,Chr
a,rs1,1
b,rs2,2
[Controls]
""")
    gsa_payload = zbuf.getvalue()
    # Manifest 2 (OmniExpress, plain csv): contains rs2, rs3 (rs2 overlaps with GSA → union = {rs1,rs2,rs3}).
    omni_payload = b"""\
[Header]
foo,bar
[Assay]
IlmnID,Name,Chr
a,rs2,2
b,rs3,3
[Controls]
"""
    # dbSNP VCF: 4 records, only rs1/rs2/rs3 are in the union.
    vcf = b"""\
##fileformat=VCFv4.2
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
1\t100\trs1\tA\tG\t.\tPASS\t.
2\t200\trs2\tC\tT\t.\tPASS\t.
3\t300\trs3\tG\tA\t.\tPASS\t.
9\t999\trs_excluded\tT\tC\t.\tPASS\t.
"""
    gz = io.BytesIO()
    with gzip.open(gz, "wb") as fh:
        fh.write(vcf)
    dbsnp_payload = gz.getvalue()

    payload_for_url = {
        fetch_assets.ILLUMINA_MANIFEST_URLS["gsa_v1"]["url"]: gsa_payload,
        fetch_assets.ILLUMINA_MANIFEST_URLS["omniexpress_v1_1"]["url"]: omni_payload,
        fetch_assets.DBSNP_URLS["GRCh37"]: dbsnp_payload,
    }

    class FakeResp:
        def __init__(self, b): self._b = io.BytesIO(b)
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=-1): return self._b.read(n)
        def readable(self): return True

    def fake_urlopen(url, timeout=None):
        if url not in payload_for_url:
            raise AssertionError(f"unexpected URL: {url}")
        return FakeResp(payload_for_url[url])

    monkeypatch.setattr(fetch_assets.urllib.request, "urlopen", fake_urlopen)
    out_path = tmp_path / "rsid_grch37.full.tsv.gz"
    fetch_assets._build_chip_union("GRCh37", out_path)

    with gzip.open(out_path, "rt") as fh:
        rows = [ln.rstrip("\n").split("\t") for ln in fh if not ln.startswith("#")]
    assert {r[0] for r in rows} == {"rs1", "rs2", "rs3"}
    # rs_excluded was in dbSNP but not in the chip union — must NOT be written.
    assert all(r[0] != "rs_excluded" for r in rows)
