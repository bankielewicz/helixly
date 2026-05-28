"""Document rendering and the single sanctioned write path.

``write_doc`` is the only function in genome-decoder that writes a canonical
document to disk. Routing every write through one chokepoint is what lets the
SPEC's rules be enforced structurally rather than by reviewer vigilance:

  1. The target may not resolve inside the archive (SPEC Rule 9).
  2. The document carries a Provenance Block (guaranteed by the ``Document``
     type) and renders a ``## Provenance Summary`` section whose header the
     Phase 7 verification greps for literally (SPEC Rule 6 / line 158).
  3. The fully-rendered text passes the aspirational-phrase blacklist gate
     before anything touches disk (SPEC Rule 1c). A hit raises and nothing is
     written — "deleted, not softened, not flagged."

Output formats follow SPEC "/skill-creator Follow-On → Output format":
working/intermediate markdown, final user-facing self-contained HTML (YAML
frontmatter as ``<meta>``; rsid/chr/pos/genotype as ``<code data-*>`` spans;
allow-list citations as ``<a data-access-date>``; semantic ``<table>``).
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import _common
from _common import Claim, Document, RemovedClaim, assert_no_aspirational, assert_not_in_archive


# --------------------------------------------------------------------------- #
# Markdown assembly
# --------------------------------------------------------------------------- #


def _provenance_summary_md(doc: Document) -> str:
    """Build the ``## Provenance Summary`` section (SPEC line 158).

    The header is emitted even when both claim lists are empty, because the
    Phase 7 verification greps ``^## Provenance Summary`` literally — a doc that
    happens to differ in no claims from its predecessor must still carry the
    header or it reads as a missing provenance block.
    """
    lines = ["## Provenance Summary", ""]
    if doc.provenance.supersedes:
        lines.append(
            f"**Supersedes.** `{doc.provenance.supersedes}` "
            f"(SHA-256 `{doc.provenance.supersedes_sha256}`)."
        )
    else:
        lines.append("**Supersedes.** none (net-new document).")
    lines.append("")

    lines.append("**Removed claims** (verbatim quote → reason removed):")
    if doc.removed_claims:
        for rc in doc.removed_claims:
            src = rc.source or "v1"
            # The attribution marker exempts the (necessarily aspirational)
            # quote from the blacklist gate — it is verbatim archive data.
            lines.append(
                f"- \"{rc.verbatim}\" [verbatim from archive: {src}] → reason: {rc.reason}"
            )
    else:
        lines.append("- none")
    lines.append("")

    lines.append("**Added claims** (one-line summary):")
    if doc.added_claims:
        for c in doc.added_claims:
            lines.append(c.summary_line())
    else:
        lines.append("- none")
    return "\n".join(lines)


def render_markdown(doc: Document) -> str:
    """Assemble the full markdown document in deterministic order."""
    parts = [
        doc.provenance.to_yaml(),
        "",
        f"# {doc.title}",
        "",
        _provenance_summary_md(doc),
        "",
    ]
    for sec in doc.sections:
        parts.append(f"## {sec.heading}")
        parts.append("")
        parts.append(sec.body_md.rstrip())
        parts.append("")
    if doc.historical_context.strip():
        parts.append("## Historical context")
        parts.append("")
        parts.append(doc.historical_context.rstrip())
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Minimal, deterministic markdown → HTML
# --------------------------------------------------------------------------- #

_RSID_CODE = re.compile(r"^rs[0-9]+$")
_VARIANT_CODE = re.compile(r"^(rs[0-9]+)\s+([0-9XYMT]+):([0-9]+)\s+([ACGTDI\-]+)$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")


def _inline_html(text: str, access_date: str) -> str:
    """Convert inline markdown to HTML, tagging genomic data and citations.

    - ``[label](url)`` → ``<a href data-access-date>`` (SPEC citation contract).
    - `` `rs123` `` → ``<code data-rsid>``; `` `rs123 1:100 AG` `` gets the full
      ``data-rsid/data-chrom/data-pos/data-genotype`` set (SPEC line 368).
    - ``**bold**`` → ``<strong>``.
    Order matters: links and code spans are extracted to placeholders first so
    their contents are not escaped twice.
    """
    placeholders: list[str] = []

    def stash(rendered: str) -> str:
        placeholders.append(rendered)
        return f"\x00{len(placeholders) - 1}\x00"

    def code_sub(m: re.Match) -> str:
        inner = m.group(1)
        var = _VARIANT_CODE.match(inner.strip())
        if var:
            rsid, chrom, pos, gt = var.groups()
            return stash(
                f'<code data-rsid="{html.escape(rsid)}" data-chrom="{html.escape(chrom)}" '
                f'data-pos="{html.escape(pos)}" data-genotype="{html.escape(gt)}">'
                f"{html.escape(inner)}</code>"
            )
        if _RSID_CODE.match(inner.strip()):
            return stash(f'<code data-rsid="{html.escape(inner.strip())}">{html.escape(inner)}</code>')
        return stash(f"<code>{html.escape(inner)}</code>")

    def link_sub(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        return stash(
            f'<a href="{html.escape(url, quote=True)}" data-access-date="{html.escape(access_date)}">'
            f"{html.escape(label)}</a>"
        )

    text = _LINK.sub(link_sub, text)
    text = _INLINE_CODE.sub(code_sub, text)
    escaped = html.escape(text)
    escaped = _BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", escaped)
    # restore placeholders
    return re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], escaped)


def _md_blocks_to_html(md: str, access_date: str) -> str:
    """Convert block-level markdown (headings, lists, tables, blockquotes,
    fenced code, paragraphs) emitted by genome-decoder to HTML. Not a general
    CommonMark engine — it covers exactly the constructs the skill produces."""
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        # fenced code
        if stripped.startswith("```"):
            j = i + 1
            buf = []
            while j < n and not lines[j].strip().startswith("```"):
                buf.append(lines[j])
                j += 1
            out.append("<pre><code>" + html.escape("\n".join(buf)) + "</code></pre>")
            i = j + 1
            continue
        # headings
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline_html(m.group(2), access_date)}</h{level}>")
            i += 1
            continue
        # table (header row then |---| separator)
        if "|" in line and i + 1 < n and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            thead = "".join(f"<th>{_inline_html(h, access_date)}</th>" for h in header)
            tbody = "".join(
                "<tr>" + "".join(f"<td>{_inline_html(c, access_date)}</td>" for c in r) + "</tr>"
                for r in rows
            )
            out.append(f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>")
            continue
        # bullet list
        if re.match(r"^\s*[-*]\s+", line):
            items = []
            while i < n and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
            lis = "".join(f"<li>{_inline_html(it, access_date)}</li>" for it in items)
            out.append(f"<ul>{lis}</ul>")
            continue
        # blockquote
        if stripped.startswith(">"):
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{_inline_html(' '.join(quote), access_date)}</blockquote>")
            continue
        # paragraph (consume until blank line or a line that starts a new block)
        start = i
        para = []
        while i < n and lines[i].strip() and not lines[i].lstrip().startswith(("#", "-", "*", ">", "|", "```")):
            para.append(lines[i].strip())
            i += 1
        if i == start:
            # The current line begins with a block-prefix character but matched
            # no block branch above (e.g. '#' not followed by a space, a stray
            # '|' that is not a table, '***'). Consume it as a one-line paragraph
            # so 'i' always advances — otherwise the loop hangs (audit finding 2).
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline_html(' '.join(para), access_date)}</p>")
    return "\n".join(out)


_HTML_CSS = """
body{font:16px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
max-width:46rem;margin:2rem auto;padding:0 1rem;color:#1a1a1a}
code{background:#f4f4f4;padding:.1em .3em;border-radius:3px;font-size:.9em}
code[data-rsid]{background:#eef6ff}
table{border-collapse:collapse;width:100%;margin:1rem 0}
th,td{border:1px solid #ddd;padding:.4rem .6rem;text-align:left}
blockquote{border-left:3px solid #ccc;margin:1rem 0;padding:.2rem 1rem;color:#555}
.provenance-meta{background:#fafafa;border:1px solid #eee;padding:1rem;font-size:.85em}
a[data-access-date]{color:#0b5fa5}
""".strip()


def render_html(doc: Document) -> str:
    """Self-contained single-file HTML (SPEC output contract).

    The Provenance Block is emitted both as ``<meta>`` tags (machine-readable
    frontmatter) and as the visible Provenance Summary section.
    """
    access_date = doc.provenance.external_sources_access_date.isoformat()
    prov = doc.provenance
    meta_tags = []
    for name in _common.PROVENANCE_FIELD_ORDER:
        value = getattr(prov, name)
        if isinstance(value, (tuple, list)):
            value = ",".join(str(v) for v in value)
        meta_tags.append(
            f'<meta name="provenance:{name}" content="{html.escape(str(value), quote=True)}">'
        )
    body_md = "\n\n".join(
        [_provenance_summary_md(doc)]
        + [f"## {s.heading}\n\n{s.body_md}" for s in doc.sections]
        + ([f"## Historical context\n\n{doc.historical_context}"] if doc.historical_context.strip() else [])
    )
    body_html = _md_blocks_to_html(body_md, access_date)
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{html.escape(doc.title)}</title>\n"
        + "\n".join(meta_tags)
        + f"\n<style>{_HTML_CSS}</style>\n</head>\n<body>\n"
        f"<h1>{html.escape(doc.title)}</h1>\n"
        + body_html
        + "\n</body>\n</html>\n"
    )


# --------------------------------------------------------------------------- #
# The single write path
# --------------------------------------------------------------------------- #


def write_doc(doc: Document, archive_dir: str | Path, *, also_html: bool = True) -> dict:
    """Render and write a canonical document — the only sanctioned writer.

    Returns a dict of the paths written. Raises before writing anything if the
    target is inside the archive (Rule 9) or the rendered text contains a non-
    exempt aspirational phrase (Rule 1c). Provenance completeness is already
    guaranteed by ``ProvenanceBlock.__post_init__`` at construction time.
    """
    assert_not_in_archive(doc.path, archive_dir)
    md = render_markdown(doc)

    # Defensive: the Provenance Summary header must be present for Phase 7 grep.
    if "## Provenance Summary" not in md:
        raise _common.IncompleteProvenanceError(
            "rendered document lacks a '## Provenance Summary' section"
        )

    assert_no_aspirational(md)  # blacklist gate — nothing is written if this raises

    target = Path(doc.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(md, encoding="utf-8")
    written = {"markdown": str(target)}

    if also_html:
        html_path = target.with_suffix(".html")
        assert_not_in_archive(html_path, archive_dir)
        html_path.write_text(render_html(doc), encoding="utf-8")
        written["html"] = str(html_path)
    return written
