"""Tests for discover.py (Phase 6 scan).

The substrate (lookup.py) is mocked; the network is exercised cache-first with
``allow_network=False`` against a pre-populated allow-list cache. Every rsID,
gene, VCV, and genotype is synthetic.
"""

from datetime import date

import _common as C
import discover
import pytest

SNAP = date(2026, 5, 29)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

# Synthetic genome genotypes returned by the mocked lookup.py.
#   rs0000001 AG — ClinVar pathogenic allele A -> carrier (pass A); gene BRCA1 -> pass B
#   rs0000002 GG — ClinVar pathogenic allele A -> NON-carrier -> excluded from A/B
#   rs0000003 CT — CPIC defining rsID present -> pass C
#   rs0000004 -- — CPIC defining rsID present but no-call -> excluded (found=n)
#   rs0000005 AG — already in the Phase-0 INDEX -> dropped at dedup
GENOTYPES = {
    "rs0000001": ("17", "43000000", "AG"),
    "rs0000002": ("1", "200000", "GG"),
    "rs0000003": ("22", "42000000", "CT"),
    "rs0000004": ("22", "42100000", "--"),
    "rs0000005": ("1", "100000", "AG"),
}


def fake_substrate(script, *args, json_out=False):
    if script != "lookup.py":
        raise AssertionError(f"unexpected substrate script: {script!r}")
    # The requested pool is the file passed after --rsids; echo all known rows whose
    # rsID was requested. Header must match the contracted columns.
    pool_path = args[args.index("--rsids") + 1]
    requested = [ln.strip() for ln in open(pool_path).read().splitlines() if ln.strip()]
    out = ["rsid\tchrom\tpos\tgenotype"]
    for r in requested:
        if r in GENOTYPES:
            c, p, g = GENOTYPES[r]
        else:
            c, p, g = "", "", "not_tested"
        out.append(f"{r}\t{c}\t{p}\t{g}")
    return "\n".join(out) + "\n"


def write_clinvar(tmp_path, rows):
    p = tmp_path / "clinvar.tsv"
    head = "rsid\tpathogenic_allele\tgene\tvcv\tsignificance"
    p.write_text("\n".join([head] + ["\t".join(r) for r in rows]) + "\n", encoding="utf-8")
    return p


def write_cpic(tmp_path, rows):
    p = tmp_path / "cpic.tsv"
    head = "gene\tdrug\tlevel\tdefining_rsids"
    p.write_text("\n".join([head] + ["\t".join(r) for r in rows]) + "\n", encoding="utf-8")
    return p


def write_index(tmp_path, rsids):
    p = tmp_path / "INDEX_genotype_truth.tsv"
    head = "rsid\tchromosome\tposition\tgenotype\tfound\tsource_docs\tdiscovered_in_phase"
    lines = [head] + ["\t".join([r, "1", "1", "AG", "y", "d.md", "0"]) for r in rsids]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def write_flagship(tmp_path, text="# Flagship\nNothing here.\n"):
    p = tmp_path / "flagship.md"
    p.write_text(text, encoding="utf-8")
    return p


def prime_cache(out_dir, source_key, identifier, *, status=200, verified=True):
    """Pre-populate the fetch_allowed cache so allow_network=False resolves offline."""
    body = C._cache_path(out_dir, source_key, identifier, SNAP, "html")
    body.parent.mkdir(parents=True, exist_ok=True)
    body.write_text("<html>cached</html>", encoding="utf-8")
    meta = body.with_suffix(body.suffix + ".meta.json")
    meta.write_text(
        '{"url": "https://example/' + identifier + '", "http_status": '
        + str(status) + ', "url_verified": ' + ("true" if verified else "false") + "}",
        encoding="utf-8",
    )


def standard_inputs(tmp_path, out):
    clinvar = write_clinvar(tmp_path, [
        ("rs0000001", "A", "BRCA1", "VCV000000001", "Pathogenic"),       # carrier + ACMG
        ("rs0000002", "A", "GENEX", "VCV000000002", "Likely pathogenic"),  # non-carrier
    ])
    cpic = write_cpic(tmp_path, [
        ("CYP2D6", "codeine", "A", "rs0000003,rs0000004"),
    ])
    index = write_index(tmp_path, ["rs0000005"])  # rs0000005 already known
    flagship = write_flagship(tmp_path)
    # cache for every identifier discover.py will verify
    for ident in ("VCV000000001", "VCV000000002"):
        prime_cache(out, "clinvar", ident)
    prime_cache(out, "cpic", "CYP2D6")
    return clinvar, cpic, index, flagship


def run(tmp_path, monkeypatch, **over):
    monkeypatch.setattr(C, "run_substrate", fake_substrate)
    out = tmp_path / "out"
    out.mkdir()
    clinvar, cpic, index, flagship = standard_inputs(tmp_path, out)
    kwargs = dict(genome=tmp_path / "g.txt", index_path=index, out_dir=out,
                  snapshot_date=SNAP, archive_flagship=flagship,
                  clinvar_path=clinvar, cpic_path=cpic, allow_network=False)
    kwargs.update(over)
    (tmp_path / "g.txt").write_text("# synthetic\n", encoding="utf-8")
    return discover.run_discover(**kwargs), out


def cand(findings, rsid):
    return next((c for c in findings["candidates"] if c["rsid"] == rsid), None)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_candidate_set_and_passes(tmp_path, monkeypatch):
    findings, _ = run(tmp_path, monkeypatch)
    rsids = [c["rsid"] for c in findings["candidates"]]
    # rs0000001 (A+B), rs0000003 (C). rs0000002 non-carrier, rs0000004 no-call,
    # rs0000005 already in Phase-0 -> none of those appear.
    assert rsids == ["rs0000001", "rs0000003"]
    assert cand(findings, "rs0000001")["passes"] == ["A", "B"]
    assert cand(findings, "rs0000003")["passes"] == ["C"]


def test_non_carrier_snv_excluded(tmp_path, monkeypatch):
    findings, _ = run(tmp_path, monkeypatch)
    assert cand(findings, "rs0000002") is None


def test_cpic_defining_rsid_absent_or_nocall_excluded(tmp_path, monkeypatch):
    findings, _ = run(tmp_path, monkeypatch)
    assert cand(findings, "rs0000004") is None  # no-call -> found=n


def test_phase0_dedup(tmp_path, monkeypatch):
    findings, _ = run(tmp_path, monkeypatch)
    assert cand(findings, "rs0000005") is None
    assert findings["summary"]["dropped_phase0"] == 0  # rs0000005 not in any pass universe

    # Now make rs0000005 a CPIC defining rsID so it enters the universe, then gets dropped.
    out = tmp_path / "out2"
    out.mkdir()
    monkeypatch.setattr(C, "run_substrate", fake_substrate)
    clinvar = write_clinvar(tmp_path, [("rs0000001", "A", "BRCA1", "VCV000000001", "Pathogenic")])
    cpic = write_cpic(tmp_path, [("CYP2D6", "codeine", "A", "rs0000003,rs0000005")])
    index = write_index(tmp_path, ["rs0000005"])
    flagship = write_flagship(tmp_path)
    prime_cache(out, "clinvar", "VCV000000001")
    prime_cache(out, "cpic", "CYP2D6")
    (tmp_path / "g.txt").write_text("# synthetic\n", encoding="utf-8")
    findings = discover.run_discover(
        genome=tmp_path / "g.txt", index_path=index, out_dir=out, snapshot_date=SNAP,
        archive_flagship=flagship, clinvar_path=clinvar, cpic_path=cpic, allow_network=False)
    assert findings["summary"]["dropped_phase0"] == 1
    assert cand(findings, "rs0000005") is None


def test_complement_strand_match(tmp_path, monkeypatch):
    """Genotype AG, pathogenic allele T -> complement A is carried -> matched (complement)."""
    monkeypatch.setattr(C, "run_substrate", fake_substrate)
    out = tmp_path / "out"
    out.mkdir()
    clinvar = write_clinvar(tmp_path, [("rs0000001", "T", "BRCA1", "VCV000000001", "Pathogenic")])
    index = write_index(tmp_path, [])
    flagship = write_flagship(tmp_path)
    prime_cache(out, "clinvar", "VCV000000001")
    (tmp_path / "g.txt").write_text("# synthetic\n", encoding="utf-8")
    findings = discover.run_discover(
        genome=tmp_path / "g.txt", index_path=index, out_dir=out, snapshot_date=SNAP,
        archive_flagship=flagship, clinvar_path=clinvar, allow_network=False)
    prov = cand(findings, "rs0000001")["clinvar"][0]
    assert prov["strand_assumption"] == "complement"
    assert prov["allele_matched"] is True


def test_net_new_grep(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "run_substrate", fake_substrate)
    out = tmp_path / "out"
    out.mkdir()
    clinvar = write_clinvar(tmp_path, [("rs0000001", "A", "BRCA1", "VCV000000001", "Pathogenic")])
    index = write_index(tmp_path, [])
    flagship = write_flagship(tmp_path, "# Flagship\nDiscusses rs0000001 already.\n")
    prime_cache(out, "clinvar", "VCV000000001")
    (tmp_path / "g.txt").write_text("# synthetic\n", encoding="utf-8")
    findings = discover.run_discover(
        genome=tmp_path / "g.txt", index_path=index, out_dir=out, snapshot_date=SNAP,
        archive_flagship=flagship, clinvar_path=clinvar, allow_network=False)
    c = cand(findings, "rs0000001")
    assert c["grep"]["observed"] == 1 and c["net_new"] is False


def test_url_verified_from_cache(tmp_path, monkeypatch):
    findings, _ = run(tmp_path, monkeypatch)
    cit = cand(findings, "rs0000001")["clinvar"][0]["citation"]
    assert cit["source_key"] == "clinvar" and cit["url_verified"] is True


def test_missing_reference_logged_and_passes_empty(tmp_path, monkeypatch):
    # Only CPIC supplied -> passes A/B empty, logged.
    monkeypatch.setattr(C, "run_substrate", fake_substrate)
    out = tmp_path / "out"
    out.mkdir()
    cpic = write_cpic(tmp_path, [("CYP2D6", "codeine", "A", "rs0000003")])
    index = write_index(tmp_path, [])
    flagship = write_flagship(tmp_path)
    prime_cache(out, "cpic", "CYP2D6")
    (tmp_path / "g.txt").write_text("# synthetic\n", encoding="utf-8")
    findings = discover.run_discover(
        genome=tmp_path / "g.txt", index_path=index, out_dir=out, snapshot_date=SNAP,
        archive_flagship=flagship, cpic_path=cpic, allow_network=False)
    assert [c["rsid"] for c in findings["candidates"]] == ["rs0000003"]
    assert any("clinvar: input not provided" in m for m in findings["log"])


def test_candidates_tsv_shape(tmp_path, monkeypatch):
    findings, out = run(tmp_path, monkeypatch)
    lines = (out / discover.CANDIDATES_TSV).read_text().splitlines()
    assert lines[0].split("\t") == list(discover.INDEX_COLUMNS)
    row = lines[1].split("\t")
    assert row[0] == "rs0000001" and row[4] == "y"
    assert row[5] == "phase6_discovery" and row[6] == "6"


def test_cache_miss_without_network_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "run_substrate", fake_substrate)
    out = tmp_path / "out"
    out.mkdir()
    clinvar = write_clinvar(tmp_path, [("rs0000001", "A", "BRCA1", "VCV000000001", "Pathogenic")])
    index = write_index(tmp_path, [])
    flagship = write_flagship(tmp_path)
    # cache deliberately NOT primed
    (tmp_path / "g.txt").write_text("# synthetic\n", encoding="utf-8")
    with pytest.raises(C.SubstrateError, match="cache miss"):
        discover.run_discover(
            genome=tmp_path / "g.txt", index_path=index, out_dir=out, snapshot_date=SNAP,
            archive_flagship=flagship, clinvar_path=clinvar, allow_network=False)


def test_outputs_byte_deterministic(tmp_path, monkeypatch):
    f1, out1 = run(tmp_path, monkeypatch)
    # second run into a fresh out dir with identical inputs
    out2 = tmp_path / "out2"
    out2.mkdir()
    monkeypatch.setattr(C, "run_substrate", fake_substrate)
    clinvar, cpic, index, flagship = standard_inputs(tmp_path, out2)
    f2 = discover.run_discover(
        genome=tmp_path / "g.txt", index_path=index, out_dir=out2, snapshot_date=SNAP,
        archive_flagship=flagship, clinvar_path=clinvar, cpic_path=cpic, allow_network=False)
    for name in (discover.FINDINGS_JSON, discover.CANDIDATES_TSV):
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes(), name
