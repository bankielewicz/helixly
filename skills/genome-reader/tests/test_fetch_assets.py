"""Regression tests for fetch_assets.py — timeout and partial-file cleanup (#8)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_assets  # noqa: E402


def test_urlopen_receives_timeout(monkeypatch, tmp_path):
    """Regression for #8: urlopen is called with an explicit timeout argument."""
    captured: dict = {}

    def fake_urlopen(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        raise RuntimeError("stop after capture")

    monkeypatch.setattr(fetch_assets.urllib.request, "urlopen", fake_urlopen)
    out_path = tmp_path / "out.tsv.gz"
    with pytest.raises(RuntimeError):
        fetch_assets._download_and_filter("http://example.invalid/x", out_path)
    assert captured.get("timeout") is not None, captured
    assert captured["timeout"] > 0, captured


def test_env_var_overrides_timeout(monkeypatch, tmp_path):
    """Regression for #8: HELIXLY_FETCH_TIMEOUT overrides the default."""
    captured: dict = {}

    def fake_urlopen(url, timeout=None):
        captured["timeout"] = timeout
        raise RuntimeError("stop")

    monkeypatch.setenv("HELIXLY_FETCH_TIMEOUT", "7")
    monkeypatch.setattr(fetch_assets.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError):
        fetch_assets._download_and_filter("http://example.invalid/x", tmp_path / "out.tsv.gz")
    assert captured["timeout"] == 7.0


def test_partial_file_removed_on_failure(monkeypatch, tmp_path):
    """Regression for #8: .part file is removed when urlopen raises."""
    def fake_urlopen(url, timeout=None):
        raise OSError("simulated network failure")

    monkeypatch.setattr(fetch_assets.urllib.request, "urlopen", fake_urlopen)
    out_path = tmp_path / "out.tsv.gz"
    part = out_path.with_suffix(out_path.suffix + ".part")
    with pytest.raises(OSError):
        fetch_assets._download_and_filter("http://example.invalid/x", out_path)
    assert not part.exists(), f".part file leaked at {part}"


def test_existing_part_file_removed_on_failure(monkeypatch, tmp_path):
    """Regression for #8: a pre-existing .part file is removed when the download fails.

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
        fetch_assets._download_and_filter("http://example.invalid/x", out_path)
    assert not part.exists(), f".part file leaked at {part}"
    assert not out_path.exists(), f"out file leaked at {out_path}"
