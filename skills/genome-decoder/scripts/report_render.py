"""HelixyAI report renderer (Workstream D2/D3).

Generates the live report — per-document pages and the index/landing hub — by
injecting structured content (``_common.ReportDocument`` / ``ReportManifest``)
into the ``HELIXY:*`` marker seams of ``assets/templates/{document,index}.html``.

The templates are the single editable source of design truth (chrome, CSS, JS,
the HelixyAI identity); this module only fills the marked dynamic regions, so
design changes need no code change. Output is self-contained (the templates load
no network assets) and deterministic (no clock/random — every value comes from
the model). All writes route through ``write_report_document`` /
``write_report_index`` which preserve the foundation gates:

  * archive guard (``assert_not_in_archive``, SPEC Rule 9),
  * a ``## Provenance Summary`` section in the markdown twin (Rule 6),
  * the aspirational-phrase blacklist gate on the markdown twin (Rule 1c) — run
    on markdown (not HTML) because the archive-attributed-blockquote exemption is
    defined over markdown ``>`` runs; the HTML is derived from the same gated
    content,
  * the standing "consult your prescribing clinician" disclaimer is always
    emitted (Rule 5).
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import _common as C

TEMPLATES_DIR = C.ASSETS_DIR / "templates"
_TEMPLATE_CACHE: dict[str, str] = {}

# Inline SVGs copied verbatim from the templates so generated markup matches.
_SVG_SHIELD = ('<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
               '<path d="M12 2l8 4v6c0 5-3.5 8-8 10-4.5-2-8-5-8-10V6z"/><path d="M9 12l2 2 4-4"/></svg>')
_SVG_ALERT = ('<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
              '<path d="M12 9v4m0 4h.01M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0z"/></svg>')
_SVG_INFO = ('<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
             '<circle cx="12" cy="12" r="10"/><path d="M12 8h.01M11 12h1v4h1"/></svg>')
_SVG_PROV_BAR = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
                 '<path d="M12 2l8 4v6c0 5-3.5 8-8 10-4.5-2-8-5-8-10V6z"/><path d="M9 12l2 2 4-4"/></svg>')

DISCLAIMER_TEXT = (
    "<b>Consult your prescribing clinician.</b> This HelixyAI report is generated "
    "from a consumer DNA export. It is not a diagnosis, prescription, or substitute "
    "for professional medical advice. Do not start, stop, or change any medication "
    "based on this document. Genotype is one of many factors influencing health and "
    "drug response."
)


# --------------------------------------------------------------------------- #
# Template loading + seam injection
# --------------------------------------------------------------------------- #


def _load_template(name: str) -> str:
    if name not in _TEMPLATE_CACHE:
        path = TEMPLATES_DIR / name
        if not path.exists():
            raise C.DecoderError(f"template not found: {path}")
        _TEMPLATE_CACHE[name] = path.read_text(encoding="utf-8")
    return _TEMPLATE_CACHE[name]


def _replace_seam(template: str, name: str, inner: str) -> str:
    """Replace content between ``<!-- HELIXY:name:START/END -->`` with ``inner``.

    Fail-closed: a missing seam raises rather than silently producing a page with
    stale template content.
    """
    pat = re.compile(
        r"<!-- HELIXY:%s:START -->.*?<!-- HELIXY:%s:END -->" % (re.escape(name), re.escape(name)),
        re.DOTALL,
    )
    if not pat.search(template):
        raise C.DecoderError(f"template seam HELIXY:{name} not found")
    replacement = f"<!-- HELIXY:{name}:START -->\n{inner}\n<!-- HELIXY:{name}:END -->"
    return pat.sub(lambda _m: replacement, template, count=1)


def esc(value) -> str:
    return html.escape(str(value), quote=True)


# --------------------------------------------------------------------------- #
# Shared component generators
# --------------------------------------------------------------------------- #


def _triple_html(t: "C.Triple") -> str:
    rs, ch, pos, gt = esc(t.rsid), esc(t.chrom), esc(t.pos), esc(t.genotype)
    return (
        '<span class="triple">'
        f'<code class="dna rs" data-rsid="{rs}" data-chrom="{ch}" data-pos="{pos}" data-genotype="{gt}">{rs}</code>'
        f'<code class="dna pos" data-rsid="{rs}" data-chrom="{ch}" data-pos="{pos}">{esc(t.pos_label)}</code>'
        f'<code class="dna gt" data-rsid="{rs}" data-genotype="{gt}">{gt}</code>'
        '</span>'
    )


def _citation_link(c: "C.Citation") -> str:
    return (
        f'<a href="{esc(c.url)}" rel="external" data-access-date="{esc(c.access_date)}">{esc(c.label)} ↗</a>'
    )


def _provenance_card(prov: "C.ProvenanceBlock", *, sources: tuple = (), source_links: tuple = ()) -> str:
    sha = esc(prov.source_genome_sha256)
    sup_sha = esc(prov.supersedes_sha256) if prov.supersedes_sha256 else "—"
    sup = esc(prov.supersedes) if prov.supersedes else "none (net-new)"
    srcs = ", ".join(source_links) if source_links else ", ".join(esc(s) for s in (sources or prov.external_sources_used))
    return (
        '<div class="prov">'
        '<div class="ph">' + _SVG_SHIELD +
        '<span class="t">Data Provenance</span><span class="v">verified chain</span></div>'
        '<dl>'
        f'<div class="row"><dt>Document</dt><dd>{esc(prov.doc_id)}</dd></div>'
        f'<div class="row"><dt>Source assembly</dt><dd>{esc(prov.source_genome_assembly)} '
        '<span style="color:var(--faint)">(hg19)</span></dd></div>'
        f'<div class="row"><dt>Source file SHA-256</dt><dd><span class="sha">{sha}</span></dd></div>'
        f'<div class="row"><dt>Supersedes</dt><dd>{sup} · SHA <span class="sha">{sup_sha}</span></dd></div>'
        f'<div class="row"><dt>Evidence sources</dt><dd>{srcs}</dd></div>'
        f'<div class="row"><dt>Access date</dt><dd>{esc(prov.external_sources_access_date)}</dd></div>'
        '</dl></div>'
    )


def _alert_table(rows: tuple) -> str:
    if not rows:
        return ""
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f'<td class="drug">{esc(r.drug)}</td>'
            f'<td class="gg">{esc(r.gene_genotype)}</td>'
            f'<td><span class="ev {C.evidence_class(r.evidence)}">{esc(r.evidence)}</span></td>'
            f'<td class="rec">{esc(r.recommendation)}</td>'
            f'<td>{_citation_link(r.citation)}</td>'
            "</tr>"
        )
    return (
        '<section class="sect" aria-labelledby="alert-h"><h2 id="alert-h">Provider Alert</h2>'
        '<div class="alert" role="region" aria-label="Actionable findings">'
        '<div class="ah">' + _SVG_ALERT +
        '<span class="t">Actionable Findings — Provider Ready</span>'
        f'<span class="meta">{len(rows)} item(s) · review before prescribing</span></div>'
        '<div class="alert-tablewrap"><table class="alert-tbl">'
        '<thead><tr><th>Drug</th><th>Gene / Genotype</th><th>Evidence</th><th>Recommendation</th><th>Source</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div></div></section>'
    )


def _finding_block(f: "C.Finding") -> str:
    tc = C.tier_class(f.tier)
    triples = "".join(_triple_html(t) for t in f.triples)
    cites = " · ".join(_citation_link(c) for c in f.citations)
    hist = ""
    if f.historical_note:
        hist = (
            '<blockquote class="hist"><span class="lbl">Historical context</span>'
            f"{esc(f.historical_note)}</blockquote>"
        )
    subtitle = f'<div class="fn">{esc(f.subtitle)}</div>' if f.subtitle else ""
    return (
        f'<div class="finding {tc}" data-tier="{f.tier}">'
        '<div class="fh"><div>'
        f'<h3>{esc(f.gene)} — {esc(f.name)}</h3>{subtitle}</div>'
        f'<div class="badges"><span class="ev {C.evidence_class(f.evidence)}">{esc(f.evidence)}</span>'
        f'<span class="tier {tc}">Tier {f.tier}</span></div></div>'
        f'<div class="triple-row">{triples}</div>'
        f'<p>{esc(f.implication)}</p>'
        f'<div class="cite">Source: {cites}</div>'
        f'{hist}</div>'
    )


def _findings_section(findings: tuple) -> str:
    if not findings:
        return ""
    counts = {1: 0, 2: 0, 3: 0}
    for f in findings:
        counts[f.tier] += 1
    chips = (
        '<div class="filters" role="group" aria-label="Filter findings by tier">'
        '<span class="fl">Filter:</span>'
        f'<button class="chip on" data-tier="all" type="button">All <span class="n">{len(findings)}</span></button>'
        f'<button class="chip" data-tier="1" type="button">Tier 1 <span class="n">{counts[1]}</span></button>'
        f'<button class="chip" data-tier="2" type="button">Tier 2 <span class="n">{counts[2]}</span></button>'
        f'<button class="chip" data-tier="3" type="button">Tier 3 <span class="n">{counts[3]}</span></button>'
        '</div>'
    )
    blocks = "".join(_finding_block(f) for f in findings)
    return (
        '<section class="sect" aria-labelledby="find-h"><h2 id="find-h">Per-Gene Findings</h2>'
        f"{chips}{blocks}</section>"
    )


def _genotype_table(rows: tuple) -> str:
    if not rows:
        return ""
    body = []
    for r in rows:
        t = r.triple
        body.append(
            "<tr>"
            f'<td><code class="dna rs" data-rsid="{esc(t.rsid)}" data-chrom="{esc(t.chrom)}" '
            f'data-pos="{esc(t.pos)}" data-genotype="{esc(t.genotype)}">{esc(t.rsid)}</code></td>'
            f'<td>{esc(t.pos_label)}</td><td>{esc(t.genotype)}</td>'
            f'<td class="gene">{esc(r.gene)}</td>'
            f'<td><span class="minitier {C.tier_class(r.tier)}">Tier {r.tier}</span></td>'
            "</tr>"
        )
    return (
        '<section class="sect" aria-labelledby="gt-h"><h2 id="gt-h">Genotype Table</h2>'
        '<div class="gtwrap"><div class="gtscroll"><table class="gt">'
        '<caption>Variants evaluated in this document</caption>'
        '<thead><tr><th scope="col">rsID</th><th scope="col">chr:pos</th><th scope="col">Genotype</th>'
        '<th scope="col">Gene</th><th scope="col">Significance</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div></div></section>'
    )


def _disclaimer() -> str:
    return (
        '<div class="disclaimer" role="note">' + _SVG_INFO +
        f'<div class="tx">{DISCLAIMER_TEXT}</div></div>'
    )


def _provenance_meta(prov: "C.ProvenanceBlock") -> str:
    sources = ", ".join(esc(s) for s in prov.external_sources_used)
    return "\n".join([
        f'<meta name="provenance:document" content="{esc(prov.doc_id)}">',
        f'<meta name="provenance:assembly" content="{esc(prov.source_genome_assembly)}">',
        f'<meta name="provenance:source_sha256" content="{esc(prov.source_genome_sha256)}">',
        f'<meta name="provenance:supersedes" content="{esc(prov.supersedes or "none")}">',
        f'<meta name="provenance:sources" content="{sources}">',
        f'<meta name="provenance:access_date" content="{esc(prov.external_sources_access_date)}">',
    ])


# --------------------------------------------------------------------------- #
# Navigation chrome (manifest-driven)
# --------------------------------------------------------------------------- #


def _sidebar(manifest: "C.ReportManifest", current_doc_id: str) -> str:
    parts = [
        '<div class="subjcard"><div class="nm">' + esc(manifest.subject_label) + '</div>'
        '<div class="meta">'
        f'<span class="k">array</span> {esc(manifest.array)}<br>'
        f'<span class="k">assembly</span> {esc(manifest.assembly)}<br>'
        f'<span class="k">generated</span> {esc(manifest.access_date)}</div></div>'
    ]
    for group in manifest.groups:
        parts.append(f'<div class="navgroup"><div class="gh">{esc(group)}</div>')
        for d in manifest.docs_in_group(group):
            cls = "navlink"
            if d.doc_id == current_doc_id:
                cls += " active"
            if d.tier == 1:
                cls += " t1"
            href = "#" if d.doc_id == current_doc_id else esc(d.filename)
            aria = ' aria-current="page"' if d.doc_id == current_doc_id else ""
            parts.append(
                f'<a class="{cls}" href="{href}"{aria}><span class="dot"></span>{esc(d.title)}</a>'
            )
        parts.append("</div>")
    return "\n".join(parts)


def _breadcrumb(rd: "C.ReportDocument") -> str:
    return (
        '<nav class="crumb" aria-label="Breadcrumb">'
        '<a href="index.html">HelixyAI Report</a><span class="sep">/</span>'
        f'<a href="index.html">{esc(rd.group)}</a><span class="sep">/</span>'
        f'<span class="cur">{esc(rd.title)}</span></nav>'
    )


def _dochead(rd: "C.ReportDocument") -> str:
    facts = "".join(f"<span>{esc(x)}</span>" for x in rd.facts)
    sub = f'<p class="sub">{esc(rd.subtitle)}</p>' if rd.subtitle else ""
    kicker = f'<div class="kicker">{esc(rd.kicker)}</div>' if rd.kicker else ""
    return (
        f'<div class="dochead">{kicker}<h1>{esc(rd.title)}</h1>{sub}'
        f'<div class="facts">{facts}</div></div>'
    )


def _pager(manifest: "C.ReportManifest", current_doc_id: str) -> str:
    i = manifest.doc_index(current_doc_id)
    docs = manifest.docs
    prev_a = next_a = ""
    if 0 <= i:
        if i > 0:
            p = docs[i - 1]
            prev_a = (f'<a class="prev" href="{esc(p.filename)}"><div class="dir">← Previous</div>'
                      f'<div class="nm">{esc(p.title)}</div></a>')
        if i < len(docs) - 1:
            n = docs[i + 1]
            next_a = (f'<a class="next" href="{esc(n.filename)}"><div class="dir">Next →</div>'
                      f'<div class="nm">{esc(n.title)}</div></a>')
    return f'<nav class="pager" aria-label="Document pager">{prev_a}{next_a}</nav>'


# --------------------------------------------------------------------------- #
# Page renderers
# --------------------------------------------------------------------------- #


def render_document_html(rd: "C.ReportDocument", manifest: "C.ReportManifest") -> str:
    """Render one analysis page by filling document.html's seams. Deterministic."""
    tpl = _load_template("document.html")
    tpl = _replace_seam(tpl, "TITLE", f"<title>{esc(rd.title)} — HelixyAI</title>")
    tpl = _replace_seam(tpl, "META", _provenance_meta(rd.provenance))
    tpl = _replace_seam(tpl, "SIDEBAR", _sidebar(manifest, rd.doc_id))
    article = "\n".join([
        _breadcrumb(rd),
        _dochead(rd),
        '<section class="sect" aria-labelledby="prov-h"><h2 id="prov-h">Provenance</h2>'
        + _provenance_card(rd.provenance) + "</section>",
        _alert_table(rd.alert_rows),
        _findings_section(rd.findings),
        _genotype_table(rd.genotype_rows),
        _disclaimer(),
        _pager(manifest, rd.doc_id),
    ])
    return _replace_seam(tpl, "ARTICLE", article)


def render_report_markdown(rd: "C.ReportDocument") -> str:
    """Markdown twin (working format) carrying ``## Provenance Summary`` (Rule 6)
    + the findings, for the blacklist gate and the Phase-7 grep. Historical notes
    render as archive-attributed blockquotes so the gate exempts them."""
    prov = rd.provenance
    lines = [prov.to_yaml(), "", f"# {esc_md(rd.title)}", "", "## Provenance Summary", ""]
    sup = prov.supersedes or "none (net-new document)"
    lines.append(f"**Supersedes.** `{sup}`"
                 + (f" (SHA-256 `{prov.supersedes_sha256}`)." if prov.supersedes_sha256 else "."))
    lines.append(f"**Findings.** {len(rd.findings)} · **Alert rows.** {len(rd.alert_rows)}")
    lines.append("")
    if rd.alert_rows:
        lines.append("## Provider Alert")
        lines.append("")
        lines.append("| Drug | Gene / Genotype | Evidence | Recommendation |")
        lines.append("|---|---|---|---|")
        for r in rd.alert_rows:
            lines.append(f"| {esc_md(r.drug)} | {esc_md(r.gene_genotype)} | {esc_md(r.evidence)} | {esc_md(r.recommendation)} |")
        lines.append("")
    for f in rd.findings:
        lines.append(f"## {esc_md(f.gene)} — {esc_md(f.name)} [Tier {f.tier}]")
        lines.append("")
        trip = " ".join(f"`{t.rsid} {t.pos_label} {t.genotype}`" for t in f.triples)
        lines.append(f"{trip} — {esc_md(f.implication)}")
        cites = "; ".join(f"[{c.label}]({c.url})" for c in f.citations)
        lines.append(f"Source: {cites}")
        if f.historical_note:
            src = prov.supersedes or "prior analysis"
            lines.append(f"> [verbatim from archive: {src}]")
            lines.append(f"> {f.historical_note}")
        lines.append("")
    lines.append("**Consult your prescribing clinician.** This report is informational and not medical advice.")
    return "\n".join(lines).rstrip() + "\n"


def esc_md(value) -> str:
    """Minimal markdown-cell escape (pipes) for the working twin."""
    return str(value).replace("|", "\\|")


# --------------------------------------------------------------------------- #
# Index page
# --------------------------------------------------------------------------- #


def _stats(manifest: "C.ReportManifest") -> str:
    s = manifest.stats
    cells = [
        (s.get("documents", len(manifest.docs)), "Documents"),
        (s.get("variants_reviewed", 0), "Variants reviewed"),
        (s.get("tier1", 0), "Tier 1 findings"),
        (manifest.assembly, "Assembly"),
    ]
    return "".join(f'<div class="stat"><div class="n">{esc(n)}</div><div class="l">{esc(l)}</div></div>'
                   for n, l in cells)


def _subject_inner(manifest: "C.ReportManifest") -> str:
    initial = esc(manifest.subject_label.strip()[:1] or "S")
    srcs = " · ".join(esc(s) for s in manifest.sources)
    return (
        '<div class="ph"><div class="av">' + initial + '</div>'
        f'<div class="nm">{esc(manifest.subject_label)}<small>Report {esc(manifest.report_id)}</small></div></div>'
        '<dl>'
        f'<div><dt>Assembly</dt><dd>{esc(manifest.assembly)}</dd></div>'
        f'<div><dt>Array</dt><dd>{esc(manifest.array)}</dd></div>'
        f'<div><dt>Access date</dt><dd>{esc(manifest.access_date)}</dd></div>'
        f'<div><dt>Sources</dt><dd>{srcs}</dd></div>'
        f'<div class="full"><dt>Source SHA-256</dt><dd>{esc(manifest.source_sha256)}</dd></div>'
        '</dl>'
    )


def _provenance_bar_dl(manifest: "C.ReportManifest") -> str:
    sup_sha = esc(manifest.supersedes_sha256) if manifest.supersedes_sha256 else "—"
    return (
        '<dl>'
        f'<div class="row"><dt>Source assembly</dt><dd>{esc(manifest.assembly)} (hg19)</dd></div>'
        f'<div class="row"><dt>Source file SHA-256</dt><dd class="sha">{esc(manifest.source_sha256)}</dd></div>'
        f'<div class="row"><dt>Supersedes</dt><dd>{esc(manifest.supersedes or "none")} · SHA <span class="sha">{sup_sha}</span></dd></div>'
        f'<div class="row"><dt>Access date</dt><dd>{esc(manifest.access_date)}</dd></div>'
        f'<div class="row"><dt>Evidence sources</dt><dd>{esc(", ".join(manifest.sources))}</dd></div>'
        f'<div class="row"><dt>Documents</dt><dd>{len(manifest.docs)} · this report</dd></div>'
        f'<div class="row"><dt>Build</dt><dd>{esc(manifest.build_label)}</dd></div>'
        '<div class="row"><dt>Status</dt><dd style="color:var(--teal-dk)">complete</dd></div>'
        '</dl>'
    )


def _highlights(manifest: "C.ReportManifest") -> str:
    s = manifest.stats
    cards = [
        ("accent", "Tier 1 findings", s.get("tier1", 0), "Strongest evidence — review with a clinician."),
        ("", "CPIC Level A", s.get("cpic_a", 0), "Highest-grade pharmacogenomic guidance."),
        ("", "Carrier flags", s.get("carriers", 0), "Recessive variants relevant to family planning."),
        ("", "Variants reviewed", s.get("variants_reviewed", 0), f"Across {len(manifest.docs)} analysis documents."),
    ]
    return "".join(
        f'<div class="hl {cls}"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div>'
        f'<div class="d">{esc(d)}</div></div>'
        for cls, k, v, d in cards
    )


def _doc_card(d: "C.ReportDoc") -> str:
    cls = "card"
    if d.available:
        cls += " ready"
    if d.tier == 1:
        cls += " t1"
    data_tier = "t1" if d.tier == 1 else ""
    ready_attr = ' data-ready="1"' if d.available else ""
    foot = []
    if d.tier_summary:
        foot.append(f'<span class="pill {C.tier_class(d.tier) if d.tier in (1,2,3) else "t3"}">{esc(d.tier_summary)}</span>')
    if d.findings_label:
        foot.append(f'<span class="pill findings">{esc(d.findings_label)}</span>')
    foot.append('<span class="arrow">→</span>')
    return (
        f'<a class="{cls}" href="{esc(d.filename)}" data-tier="{data_tier}"{ready_attr} '
        f'data-name="{esc(d.search_terms)}">'
        f'<div class="top"><span class="ic">${{ICON_{esc(d.icon_token)}}}</span><span class="num">{esc(d.number)}</span></div>'
        f'<h3>{esc(d.title)}</h3><p>{esc(d.blurb)}</p>'
        f'<div class="foot">{"".join(foot)}</div></a>'
    )


def _doc_grid(manifest: "C.ReportManifest") -> str:
    parts = []
    for group in manifest.groups:
        docs = manifest.docs_in_group(group)
        cards = "".join(_doc_card(d) for d in docs)
        parts.append(
            f'<div class="grp" data-group="{esc(group)}">'
            f'<div class="gh">{esc(group)} <span class="gn">{len(docs)} docs</span></div>'
            f'<div class="grid">{cards}</div></div>'
        )
    return "\n".join(parts)


def _index_meta(manifest: "C.ReportManifest") -> str:
    return "\n".join([
        '<meta name="provenance:report" content="HelixyAI Genome Report">',
        f'<meta name="provenance:assembly" content="{esc(manifest.assembly)}">',
        f'<meta name="provenance:source_sha256" content="{esc(manifest.source_sha256)}">',
        f'<meta name="provenance:supersedes" content="{esc(manifest.supersedes or "none")}">',
        f'<meta name="provenance:sources" content="{esc(", ".join(manifest.sources))}">',
        f'<meta name="provenance:access_date" content="{esc(manifest.access_date)}">',
        f'<meta name="provenance:subject" content="{esc(manifest.subject_label)}">',
        f'<meta name="provenance:documents" content="{len(manifest.docs)}">',
    ])


def render_index_html(manifest: "C.ReportManifest") -> str:
    """Render the index/landing hub by filling index.html's seams. Deterministic."""
    tpl = _load_template("index.html")
    tpl = _replace_seam(tpl, "TITLE", f"<title>HelixyAI — Genome Report · {esc(manifest.subject_label)}</title>")
    tpl = _replace_seam(tpl, "META", _index_meta(manifest))
    tpl = _replace_seam(tpl, "STATS", _stats(manifest))
    tpl = _replace_seam(tpl, "SUBJECT", _subject_inner(manifest))
    tpl = _replace_seam(tpl, "PROVENANCE", _provenance_bar_dl(manifest))
    tpl = _replace_seam(tpl, "HIGHLIGHTS", _highlights(manifest))
    tpl = _replace_seam(tpl, "GRID", _doc_grid(manifest))
    return tpl


# --------------------------------------------------------------------------- #
# Write paths (gated)
# --------------------------------------------------------------------------- #


def _doc_filename(rd: "C.ReportDocument", manifest: "C.ReportManifest") -> str:
    idx = manifest.doc_index(rd.doc_id)
    if idx >= 0:
        return manifest.docs[idx].filename
    return f"{rd.title}.html"


def write_report_document(rd: "C.ReportDocument", manifest: "C.ReportManifest",
                          out_dir, archive_dir) -> dict:
    """Render + write one document's markdown twin and designed HTML.

    Gates (fail before any write): archive guard; ``## Provenance Summary`` present;
    blacklist gate on the markdown twin.
    """
    out_dir = Path(out_dir)
    md = render_report_markdown(rd)
    if "## Provenance Summary" not in md:
        raise C.IncompleteProvenanceError("markdown twin lacks '## Provenance Summary' (SPEC Rule 6)")
    C.assert_no_aspirational(md)  # Rule 1c — raises AspirationalClaimDetected

    html_name = _doc_filename(rd, manifest)
    html_path = out_dir / html_name
    md_path = out_dir / (Path(html_name).stem + ".md")
    C.assert_not_in_archive(html_path, archive_dir)
    C.assert_not_in_archive(md_path, archive_dir)

    out_dir.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(render_document_html(rd, manifest), encoding="utf-8")
    return {"markdown": str(md_path), "html": str(html_path)}


def write_report_index(manifest: "C.ReportManifest", out_dir, archive_dir=None) -> dict:
    out_dir = Path(out_dir)
    index_path = out_dir / "index.html"
    if archive_dir is not None:
        C.assert_not_in_archive(index_path, archive_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path.write_text(render_index_html(manifest), encoding="utf-8")
    return {"html": str(index_path)}
