"""Public API smoke test: import from consumer_dna and validate the contract."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from consumer_dna import detect_consumer_dna_build, iter_consumer_dna  # noqa: E402


def test_public_import_exposes_callables():
    assert callable(iter_consumer_dna)
    assert callable(detect_consumer_dna_build)


def test_iter_consumer_dna_yields_4_tuples(fixtures_dir):
    rows = list(iter_consumer_dna(fixtures_dir / "23andme_sample.txt"))
    assert rows, "expected at least one genotype row"
    for row in rows:
        assert isinstance(row, tuple) and len(row) == 4
        assert all(isinstance(field, str) for field in row)
    table = {r[0]: r for r in rows}
    assert table["rs1"] == ("rs1", "1", "100", "AG")
    assert table["rs3"][3] == "GG"


def test_detect_consumer_dna_build(fixtures_dir):
    assert detect_consumer_dna_build(fixtures_dir / "23andme_sample.txt") == "GRCh37"
