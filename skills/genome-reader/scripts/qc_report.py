#!/usr/bin/env python3
"""Per-FASTQ QC report rendered as a single self-contained HTML file.

Sections: per-base quality boxplot, per-sequence quality histogram, length
distribution, GC distribution, N content, top 20 overrepresented sequences.
"""

from __future__ import annotations

import base64
import html as html_lib
import io
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import die, open_maybe_gzip, phred_offset  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _read_fastq(path: str):
    with open_maybe_gzip(path, "rt") as fh:
        while True:
            h = fh.readline()
            if not h:
                break
            seq = fh.readline().rstrip("\n")
            _ = fh.readline()
            qual = fh.readline().rstrip("\n")
            if not qual:
                break
            yield seq, qual


def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] in {"-h", "--help"}:
        print("usage: qc_report.py <fastq>", file=sys.stderr)
        return 2
    path = argv[1]
    if not Path(path).exists():
        die(f"no such file: {path}")

    per_base_quals: list[list[int]] = []
    per_read_mean: list[float] = []
    lengths: list[int] = []
    gc_pct: list[float] = []
    n_per_pos: list[int] = []
    pos_count: list[int] = []
    n_count_total = 0
    base_total = 0
    seq_counter: Counter = Counter()
    min_qchar = 255
    max_qchar = 0

    for seq, qual in _read_fastq(path):
        if not seq or not qual:
            continue
        L = len(seq)
        lengths.append(L)
        gc = (seq.count("G") + seq.count("C") + seq.count("g") + seq.count("c"))
        gc_pct.append(round(100 * gc / L, 2))
        n_count_total += seq.upper().count("N")
        base_total += L
        seq_counter[seq] += 1

        # Per-position N content (seq-indexed).
        while len(n_per_pos) < L:
            n_per_pos.append(0)
            pos_count.append(0)
        for i, b in enumerate(seq):
            pos_count[i] += 1
            if b in "Nn":
                n_per_pos[i] += 1

        # Per-position quality (qual-indexed; may exceed L on malformed reads).
        rq: list[int] = []
        for i, c in enumerate(qual):
            v = ord(c)
            if v < min_qchar:
                min_qchar = v
            if v > max_qchar:
                max_qchar = v
            rq.append(v)
            while len(per_base_quals) <= i:
                per_base_quals.append([])
            per_base_quals[i].append(v)
        if rq:
            per_read_mean.append(statistics.fmean(rq))

    if not lengths:
        die("no reads in input")
    offset, _ = phred_offset(min_qchar, max_qchar)

    figs_b64: dict[str, str] = {}

    # Per-base quality boxplot (cap at first 300 cycles)
    pb = per_base_quals[:300]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.boxplot([[v - offset for v in col] for col in pb], showfliers=False)
    ax.set_xlabel("position in read")
    ax.set_ylabel(f"Phred (offset {offset})")
    ax.set_title("Per-base quality")
    figs_b64["per_base_q"] = _fig_to_b64(fig)

    # Per-sequence quality histogram
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist([m - offset for m in per_read_mean], bins=40)
    ax.set_xlabel("mean read quality")
    ax.set_ylabel("read count")
    ax.set_title("Per-sequence mean quality")
    figs_b64["per_seq_q"] = _fig_to_b64(fig)

    # Length distribution
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(lengths, bins=40)
    ax.set_xlabel("read length")
    ax.set_ylabel("count")
    ax.set_title("Read length distribution")
    figs_b64["lengths"] = _fig_to_b64(fig)

    # GC distribution
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(gc_pct, bins=40, range=(0, 100))
    ax.set_xlabel("GC%")
    ax.set_ylabel("read count")
    ax.set_title("Per-read GC%")
    figs_b64["gc"] = _fig_to_b64(fig)

    n_pct = [100 * n / c if c else 0 for n, c in zip(n_per_pos, pos_count)]
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.plot(range(1, len(n_pct) + 1), n_pct)
    ax.set_xlabel("position in read")
    ax.set_ylabel("% N")
    ax.set_ylim(0, max(5, max(n_pct) * 1.2 if n_pct else 1))
    ax.set_title("Per-position N content")
    figs_b64["n_content"] = _fig_to_b64(fig)

    top_seqs = seq_counter.most_common(20)
    n_rate = 100 * n_count_total / base_total if base_total else 0

    out_path = Path(path).with_suffix(Path(path).suffix + ".qc.html")
    if out_path.name.endswith(".gz.qc.html"):
        out_path = Path(str(out_path).replace(".gz.qc.html", ".qc.html"))

    rows = "".join(
        f"<tr><td>{i+1}</td><td>{html_lib.escape(s[:120])}</td><td>{c}</td></tr>"
        for i, (s, c) in enumerate(top_seqs)
    )

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>QC report — {html_lib.escape(Path(path).name)}</title>
<style>
body{{font:14px/1.4 system-ui,sans-serif;max-width:1000px;margin:2em auto;padding:0 1em}}
h1,h2{{font-weight:600}} h2{{margin-top:2em;border-bottom:1px solid #ddd;padding-bottom:.3em}}
img{{max-width:100%;height:auto}} table{{border-collapse:collapse;width:100%}}
td,th{{padding:.4em .6em;border-bottom:1px solid #eee;text-align:left;font-family:monospace;font-size:12px}}
dt{{font-weight:600}} dd{{margin:0 0 .4em 1em}}
</style></head><body>
<h1>QC report</h1>
<dl>
<dt>file</dt><dd>{html_lib.escape(path)}</dd>
<dt>reads</dt><dd>{len(lengths)}</dd>
<dt>total bases</dt><dd>{base_total}</dd>
<dt>N rate</dt><dd>{n_rate:.4f}%</dd>
<dt>Phred encoding</dt><dd>Phred+{offset}</dd>
</dl>
<h2>Per-base quality</h2><img src="data:image/png;base64,{figs_b64['per_base_q']}">
<h2>Per-sequence mean quality</h2><img src="data:image/png;base64,{figs_b64['per_seq_q']}">
<h2>Read length distribution</h2><img src="data:image/png;base64,{figs_b64['lengths']}">
<h2>Per-read GC%</h2><img src="data:image/png;base64,{figs_b64['gc']}">
<h2>Per-position N content</h2><img src="data:image/png;base64,{figs_b64['n_content']}">
<h2>Top 20 overrepresented sequences</h2>
<table><tr><th>#</th><th>sequence</th><th>count</th></tr>{rows}</table>
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
