"""Shared contract and helpers for genome-decoder scripts.

This module is the load-bearing foundation of the skill. It encodes, as
Python invariants, the parts of ``SPEC_genome_audit_workflow.md`` that every
phase depends on:

- the Provenance Block (SPEC "Provenance Block Template") as a frozen dataclass
  that *cannot be constructed* with a missing required field;
- the ``Claim`` / ``Document`` types that make a Provenance Block mandatory at
  the type level rather than as a convention;
- the substrate contract with ``genome-reader`` (SPEC "Phase 7 Amendment");
- the citation allow-list + per-request cache (SPEC "Evidence Sources" and the
  determinism contract on SPEC line 370);
- the aspirational-phrase blacklist gate (SPEC "Appendix: Aspirational Phrase
  Blacklist").

The design choice throughout: make the SPEC's rules structural. A document that
violates a rule should fail to *construct* or fail to *write*, not merely fail a
later review. That is why the dataclasses are frozen and validated in
``__post_init__`` and why ``render.write_doc`` is the only write path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Literal, Optional, Sequence

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_ROOT / "assets"
BLACKLIST_FILE = ASSETS_DIR / "blacklist_phrases.txt"
ALLOWLIST_FILE = ASSETS_DIR / "allowlist_sources.json"


def genome_reader_path() -> Path:
    """Resolve the genome-reader substrate skill.

    Reads ``GENOME_READER_PATH`` from the environment; defaults to the sibling
    skill directory ``../genome-reader`` relative to this skill root. This is
    SPEC open-question 9 ("genome-reader install convention") resolved in favor
    of an env var with a sibling-directory default, so the common case needs no
    configuration while CI / alternate layouts can override.
    """
    env = os.environ.get("GENOME_READER_PATH")
    if env:
        return Path(env).expanduser().resolve()
    return (SKILL_ROOT.parent / "genome-reader").resolve()


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class DecoderError(Exception):
    """Base class for every genome-decoder failure."""


class SubstrateError(DecoderError):
    """genome-reader was missing, the wrong version, or returned unusable output."""


class DriftError(DecoderError):
    """A recorded hash / line count no longer matches the live file (SPEC Rule, STOP)."""


class AllowlistError(DecoderError):
    """A citation source is not in ``allowlist_sources.json`` (SPEC Evidence Sources)."""


class IncompleteProvenanceError(DecoderError):
    """A Provenance Block is missing a SPEC-required field (SPEC Rule 6)."""


class AspirationalClaimDetected(DecoderError):
    """The blacklist gate found a non-exempt aspirational phrase (SPEC Rule 1c)."""

    def __init__(self, hits: "Sequence[BlacklistHit]"):
        self.hits = list(hits)
        lines = "; ".join(f"line {h.lineno}: {h.token!r}" for h in self.hits)
        super().__init__(f"aspirational phrasing blocks write: {lines}")


class ArchiveWriteError(DecoderError):
    """A write was attempted inside the immutable archive directory (SPEC Rule 9)."""


class GitGuardError(DecoderError):
    """A git operation was attempted in a non-git directory (SPEC Rule 10)."""


# --------------------------------------------------------------------------- #
# Hashing & filesystem guards
# --------------------------------------------------------------------------- #


def sha256_file(path: str | os.PathLike) -> str:
    """SHA-256 of a file, lowercase hex. Used for source-genome + INDEX drift."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def assert_not_in_archive(target: str | os.PathLike, archive_dir: str | os.PathLike) -> None:
    """Refuse any write whose resolved path lives under the archive (SPEC Rule 9).

    The archive is the immutable historical baseline. We resolve both paths so a
    relative ``../`` or a symlink cannot sneak a write inside it.
    """
    t = Path(target).resolve()
    a = Path(archive_dir).resolve()
    try:
        t.relative_to(a)
    except ValueError:
        return  # target is outside the archive — allowed
    raise ArchiveWriteError(
        f"refusing to write {t} — it resolves inside the immutable archive {a} "
        "(SPEC Non-Negotiable Rule 9)"
    )


def is_git_repo(path: str | os.PathLike) -> bool:
    """True if ``path`` (or an ancestor) is inside a git work tree.

    SPEC Rule 10 forbids git operations in non-git directories. Callers must
    gate every git invocation on this. We shell out to ``git`` so the answer
    matches what git itself would do (worktrees, submodules), and treat a
    missing git binary as "not a repo" rather than crashing.
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


# --------------------------------------------------------------------------- #
# genome-reader substrate contract  (SPEC "Phase 7 Amendment")
# --------------------------------------------------------------------------- #


def run_substrate(script: str, *args: str, json_out: bool = False) -> dict | str:
    """Invoke a genome-reader script and return its stdout.

    Single chokepoint for the substrate so a future genome-reader refactor is
    localized here (design-doc §2). ``script`` is a bare filename such as
    ``"summarize.py"``; ``args`` are passed through verbatim.

    With ``json_out=True`` the stdout is parsed as JSON and returned as a dict;
    otherwise the raw stdout string is returned. A non-zero exit, a missing
    script, or unparseable JSON raises ``SubstrateError`` — never a silent
    fallback, because every value the substrate returns feeds drift detection
    or the INDEX, where a wrong-but-plausible value is worse than a stop.
    """
    gr = genome_reader_path()
    script_path = gr / "scripts" / script
    if not script_path.exists():
        raise SubstrateError(
            f"genome-reader script not found: {script_path}. Set GENOME_READER_PATH "
            f"or install genome-reader as a sibling skill. {substrate_version_note()}"
        )
    python = _substrate_python(gr)
    cmd = [python, str(script_path), *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as e:  # noqa: BLE001
        raise SubstrateError(f"could not run {' '.join(cmd)}: {e}") from e
    if r.returncode != 0:
        raise SubstrateError(
            f"genome-reader {script} exited {r.returncode}: {r.stderr.strip()}"
        )
    if json_out:
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError as e:
            raise SubstrateError(
                f"genome-reader {script} did not return JSON: {e}\n{r.stdout[:500]}"
            ) from e
    return r.stdout


def _substrate_python(gr: Path) -> str:
    """Prefer genome-reader's own venv interpreter; fall back to ours."""
    cand = gr / ".venv" / "bin" / "python"
    if cand.exists():
        return str(cand)
    cand_win = gr / ".venv" / "Scripts" / "python.exe"
    if cand_win.exists():
        return str(cand_win)
    return sys.executable


def substrate_version_note() -> str:
    """The minimum genome-reader capability genome-decoder depends on.

    SPEC open-question 7 (version pinning) is resolved pragmatically: genome-
    reader exposes no ``--version``, so we pin by *capability* — the presence of
    ``lookup.py --columns`` (PR #23). ``assets/README.md`` records the git SHA;
    this string is what users see when the substrate is missing or too old.
    """
    return (
        "genome-decoder requires genome-reader with `lookup.py --columns "
        "rsid,chrom,pos,genotype` (PR #23 or later); see assets/README.md."
    )


# Verified substrate output shapes (captured 2026-05-28 against genome-reader's
# own fixtures, matching SPEC validation table lines 462-468):
#   identify.py            -> {"format": "consumer_dna:23andme", "size_bytes": int, ...}
#   summarize.py --json    -> {"format", "snp_count": int, "build": "GRCh37"|"GRCh38",
#                              "chromosome_distribution": {...}, "no_call_rate": float}
#   lookup.py --columns rsid,chrom,pos,genotype -> TSV with header
#       "rsid\tchrom\tpos\tgenotype"; present rows "rs1\t1\t100\tAG";
#       absent rows render "rsXXX\t\t\tnot_tested" (empty chrom/pos).
LOOKUP_COLUMNS = "rsid,chrom,pos,genotype"
NOT_TESTED = "not_tested"
NO_CALL = "--"


def genotype_found(genotype: str) -> bool:
    """The INDEX ``found`` column: y when the chip actually called this site.

    A site is *found* when the source genome reports a real genotype — i.e. the
    rsid is present (not ``not_tested``) and the call is not a no-call (``--``).
    """
    g = genotype.strip()
    return g not in ("", NOT_TESTED, NO_CALL)


# --------------------------------------------------------------------------- #
# Citation allow-list + per-request cache  (SPEC "Evidence Sources" + line 370)
# --------------------------------------------------------------------------- #


def load_allowlist() -> dict:
    with open(ALLOWLIST_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def allowlist_cache_dir(output_dir: str | os.PathLike) -> Path:
    return Path(output_dir) / ".allowlist_cache"


def _cache_path(output_dir: Path, source_key: str, identifier: str, snapshot_date: date, ext: str) -> Path:
    """Content-addressed cache filename: ``<identifier>_<YYYYMMDD>.<ext>``.

    The date is the *snapshot date* (an explicit input — see ``fetch_allowed``),
    not the wall clock, so the determinism contract on SPEC line 370 holds: same
    inputs + same snapshot date => same cache filenames => same provenance
    ``external_sources_access_date``. The cache directory *is* the access-date
    ledger; the renderer reads the date back off the filename.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", identifier)
    stamp = snapshot_date.strftime("%Y%m%d")
    return allowlist_cache_dir(output_dir) / source_key / f"{safe}_{stamp}.{ext}"


@dataclass(frozen=True)
class FetchResult:
    """The outcome of an allow-listed fetch, cached and replayable.

    ``url_verified`` records whether the URL resolved on the snapshot date (SPEC
    Rule 8): a non-2xx response is recorded, not raised, and the citation is
    later rendered with ``url_verified: false``.
    """

    source_key: str
    identifier: str
    url: str
    access_date: date
    http_status: Optional[int]
    url_verified: bool
    body_path: Path

    @property
    def body(self) -> str:
        return self.body_path.read_text(encoding="utf-8")


def fetch_allowed(
    source_key: str,
    identifier: str,
    output_dir: str | os.PathLike,
    snapshot_date: date,
    *,
    allow_network: bool = True,
    timeout: float = 20.0,
) -> FetchResult:
    """Fetch an allow-listed source, cache-first and deterministic.

    This is the *only* sanctioned network entry point. Every WebFetch-style call
    in every phase routes through here so that (a) off-list sources are rejected
    (SPEC Evidence Sources) and (b) the determinism contract holds.

    Behaviour:
      1. ``source_key`` must be a key in ``allowlist_sources.json`` else
         ``AllowlistError`` — there is no code path that fetches an off-list URL.
      2. If a cache file for ``(source_key, identifier, snapshot_date)`` exists,
         it is returned with *no network call*. Re-running on the same snapshot
         date is therefore offline and byte-identical.
      3. Otherwise, if ``allow_network`` is True, the URL is fetched once and the
         body + metadata are written to the cache. A non-2xx (or a transport
         error) is recorded as ``url_verified=False`` rather than raised.
      4. If the cache misses and ``allow_network`` is False, ``SubstrateError``
         is raised naming the source — tests and reproducible reruns set
         ``allow_network=False`` and pre-populate the cache.

    ``snapshot_date`` is a required, explicit argument (not ``date.today()``);
    callers thread it from ``--snapshot-date`` so the same date in produces the
    same bytes out, with no clock-monkeypatching needed in tests.
    """
    out = Path(output_dir)
    allow = load_allowlist()
    if source_key not in allow:
        raise AllowlistError(
            f"source {source_key!r} is not in the citation allow-list "
            f"({', '.join(sorted(allow))}). SPEC: only Evidence-Sources entries "
            "may back a clinical claim."
        )
    spec = allow[source_key]
    ext = spec.get("ext", "json")
    url = _format_url(spec["url_template"], identifier)

    body_path = _cache_path(out, source_key, identifier, snapshot_date, ext)
    meta_path = body_path.with_suffix(body_path.suffix + ".meta.json")

    if body_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return FetchResult(
            source_key=source_key,
            identifier=identifier,
            url=meta.get("url", url),
            access_date=snapshot_date,
            http_status=meta.get("http_status"),
            url_verified=bool(meta.get("url_verified", False)),
            body_path=body_path,
        )

    if not allow_network:
        raise SubstrateError(
            f"cache miss for {source_key}/{identifier} on {snapshot_date} and "
            "network is disabled. Pre-populate the allow-list cache or rerun with "
            "network enabled."
        )

    status, body, ok = _http_get(url, timeout=timeout)
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_text(body, encoding="utf-8")
    meta = {
        "source_key": source_key,
        "identifier": identifier,
        "url": url,
        "snapshot_date": snapshot_date.isoformat(),
        "http_status": status,
        "url_verified": ok,
    }
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return FetchResult(
        source_key=source_key,
        identifier=identifier,
        url=url,
        access_date=snapshot_date,
        http_status=status,
        url_verified=ok,
        body_path=body_path,
    )


def _format_url(template: str, identifier: str) -> str:
    """Fill a URL template. Templates use ``{id}`` for the raw identifier and
    ``{id_numeric}`` for its digits-only form (ClinVar VCV numbers, PMIDs)."""
    id_numeric = re.sub(r"\D", "", identifier)
    return template.replace("{id_numeric}", id_numeric).replace("{id}", identifier)


def _http_get(url: str, timeout: float) -> tuple[Optional[int], str, bool]:
    """Single HTTP GET. Returns (status, body, url_verified).

    ``requests`` is imported lazily so the foundation (and the entire test
    suite, which runs cache-first) does not require the network stack to be
    importable. A transport failure returns ``(None, "", False)`` so SPEC Rule 8
    can record ``url_verified: false`` instead of aborting the run.
    """
    try:
        import requests  # local import — keeps offline paths dependency-free
    except ImportError as e:  # pragma: no cover - exercised only when requests absent
        raise SubstrateError(
            "the 'requests' package is required for live fetches; install "
            "requirements.txt or pre-populate the allow-list cache"
        ) from e
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "genome-decoder"})
        return resp.status_code, resp.text, 200 <= resp.status_code < 300
    except requests.RequestException:
        return None, "", False


# --------------------------------------------------------------------------- #
# Aspirational-phrase blacklist gate  (SPEC "Appendix: Aspirational Phrase Blacklist")
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BlacklistHit:
    lineno: int
    token: str
    line: str


# Stable-terminology terms (SPEC "Stable-terminology exemption"). The word
# ``likely`` is permitted only inside these hyphenated ClinVar classes, and only
# with a same-line citation.
_STABLE_LIKELY = ("likely-pathogenic", "likely-benign")
_CITATION_MARKERS = ("PMID", "VCV", "RCV", "CPIC", "PharmGKB", "FDA", "GCST", "rs", "gnomAD")


def _load_blacklist_patterns() -> list[tuple[str, re.Pattern]]:
    """Compile the blacklist file into (token, regex) pairs.

    Each non-comment, non-blank line of ``blacklist_phrases.txt`` is one ERE
    alternative copied from the SPEC enforcement regex. We compile case-
    insensitively, satisfying SPEC Rule 1c and the hard-won lesson recorded in
    feedback memory 'blacklist-grep-case-insensitive' — capitalized natural-
    language variants ("Likely normal") must be caught too.
    """
    pats: list[tuple[str, re.Pattern]] = []
    for raw in BLACKLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pats.append((line, re.compile(line, re.IGNORECASE)))
    return pats


def _fenced_code_line_flags(lines: Sequence[str]) -> list[bool]:
    """Mark which lines sit inside a ``` fenced code block (SPEC exemption)."""
    inside = False
    flags: list[bool] = []
    for ln in lines:
        if ln.lstrip().startswith("```"):
            flags.append(True)  # the fence line itself is code
            inside = not inside
            continue
        flags.append(inside)
    return flags


def _archive_quote_line_flags(lines: Sequence[str]) -> list[bool]:
    """Flag every line of an archive-attributed blockquote (SPEC Rule 1).

    SPEC Rule 1 permits aspirational tokens "inside verbatim quotes from archive
    docs (clearly demarcated with markdown blockquote ``>`` and an inline
    ``[verbatim from archive...]`` attribution)" — i.e. the whole *blockquote* is
    exempt, not merely the line carrying the attribution marker. A re-audit's
    medical-notes and checkpoint-log rebuilds preserve multi-line attributed
    quotes whose continuation lines carry aspirational wording; without this the
    renderer's write gate would refuse to write them.

    A blockquote run is a maximal run of consecutive lines whose ``lstrip``
    starts with ``>`` (matching ``render._md_blocks_to_html``'s grouping). The run
    is exempt if *any* of its lines carries the attribution marker, so the rule
    holds regardless of which ``>`` line the marker sits on.
    """
    flags = [False] * len(lines)
    i, n = 0, len(lines)
    while i < n:
        if lines[i].lstrip().startswith(">"):
            j = i
            while j < n and lines[j].lstrip().startswith(">"):
                j += 1
            if any("[verbatim from archive" in lines[k] for k in range(i, j)):
                for k in range(i, j):
                    flags[k] = True
            i = j
        else:
            i += 1
    return flags


def _strip_inline_code(line: str) -> str:
    """Remove `inline-code` spans so a token cited as data inside backticks does
    not count as natural-language hedging (SPEC exemption)."""
    return re.sub(r"`[^`]*`", " ", line)


def _section_is_exempt(heading: str) -> bool:
    """Glossary / Appendix headings are exempt (SPEC 'Out of scope')."""
    h = heading.lower()
    return "glossary" in h or "appendix" in h


def find_blacklist_hits(text: str) -> list[BlacklistHit]:
    """Return non-exempt aspirational-phrase hits in ``text``.

    The grep is the easy half; the work is the exemption filter. A token is
    *exempt* (per the SPEC) when it appears:
      - inside a fenced code block, or inside an inline-code span (cited as data);
      - inside a Glossary or Appendix section;
      - inside an archive-attributed blockquote (a ``>`` line carrying a
        ``[verbatim from archive`` attribution);
      - as part of a stable ClinVar class (``likely-pathogenic`` /
        ``likely-benign``) on a line that also carries a citation marker.

    Everything else is a real hit and will block the write.
    """
    patterns = _load_blacklist_patterns()
    lines = text.splitlines()
    code_flags = _fenced_code_line_flags(lines)
    archive_quote_flags = _archive_quote_line_flags(lines)
    current_heading = ""
    hits: list[BlacklistHit] = []

    for i, raw_line in enumerate(lines, start=1):
        if raw_line.lstrip().startswith("#") and raw_line.lstrip().lstrip("#").strip():
            current_heading = raw_line.lstrip("#").strip()
        if code_flags[i - 1]:
            continue  # fenced code block — exempt
        if _section_is_exempt(current_heading):
            continue  # Glossary / Appendix — exempt
        # Archive-attributed verbatim quote — exempt (SPEC Rule 1). The
        # attribution marker is the load-bearing signal that the content is a
        # verbatim archive quote being cited as data, not hedging being used.
        # Two exemption forms:
        #   (a) a multi-line blockquote whose run carries the marker — the whole
        #       run is exempt (archive_quote_flags), so continuation '>' lines
        #       that lack the marker are not flagged; and
        #   (b) a single line carrying the marker inline — e.g. the Provenance
        #       Summary's "Removed claims" bullets, whose whole job is to quote
        #       the removed (aspirational) v1 text on one line.
        if archive_quote_flags[i - 1]:
            continue
        if "[verbatim from archive" in raw_line:
            continue

        scan_target = _strip_inline_code(raw_line)  # inline-code spans removed
        has_citation = any(m in raw_line for m in _CITATION_MARKERS)
        for token, pat in patterns:
            for m in pat.finditer(scan_target):
                matched = m.group(0)
                # Stable-terminology exemption for 'likely'.
                if matched.lower().startswith("likely"):
                    window = scan_target[max(0, m.start() - 1): m.end() + 12].lower()
                    if any(cls in window for cls in _STABLE_LIKELY) and has_citation:
                        continue
                hits.append(BlacklistHit(lineno=i, token=matched, line=raw_line.strip()))
    return hits


def assert_no_aspirational(text: str) -> None:
    """Raise ``AspirationalClaimDetected`` if any non-exempt hit exists.

    Called by ``render.write_doc`` before anything touches disk: a document with
    aspirational phrasing is never written, per SPEC Rule 1 ("deleted ... not
    softened, not flagged, not commented out").
    """
    hits = find_blacklist_hits(text)
    if hits:
        raise AspirationalClaimDetected(hits)


# --------------------------------------------------------------------------- #
# Provenance Block  (SPEC "Provenance Block Template")
# --------------------------------------------------------------------------- #

# SPEC template field order. The renderer emits YAML in exactly this order so
# output is deterministic and the Phase 7 grep finds fields predictably.
PROVENANCE_FIELD_ORDER = (
    "doc_id",
    "produced_by",
    "produced_on",
    "phase",
    "source_genome_path",
    "source_genome_sha256",
    "source_genome_assembly",
    "source_genome_line_count_verified",
    "genotype_index_path",
    "genotype_index_sha256",
    "supersedes",
    "supersedes_sha256",
    "removed_claims_count",
    "added_claims_count",
    "external_sources_used",
    "external_sources_access_date",
)

# Fields that may legitimately be null: a doc with no archived predecessor
# (e.g. a net-new findings doc) has no ``supersedes``. Everything else is
# required-non-empty per SPEC Rule 6 ("Missing block = file rejected").
_OPTIONAL_PROVENANCE_FIELDS = {"supersedes", "supersedes_sha256"}

Assembly = Literal["GRCh37", "GRCh38", "other"]


@dataclass(frozen=True)
class ProvenanceBlock:
    doc_id: str
    produced_by: str
    produced_on: date
    phase: int
    source_genome_path: str
    source_genome_sha256: str
    source_genome_assembly: Assembly
    source_genome_line_count_verified: int
    genotype_index_path: str
    genotype_index_sha256: str
    removed_claims_count: int
    added_claims_count: int
    external_sources_used: tuple[str, ...]
    external_sources_access_date: date
    supersedes: Optional[str] = None
    supersedes_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        """Enforce SPEC Rule 6 at construction time.

        A ``ProvenanceBlock`` cannot exist with a missing required field, so a
        ``Document`` carrying one is guaranteed compliant before render. This is
        the difference between an invariant and a polite suggestion.
        """
        for name in PROVENANCE_FIELD_ORDER:
            if name in _OPTIONAL_PROVENANCE_FIELDS:
                continue
            value = getattr(self, name)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise IncompleteProvenanceError(
                    f"Provenance Block field {name!r} is empty (SPEC Rule 6)"
                )
        if not 0 <= self.phase <= 7:
            raise IncompleteProvenanceError(f"phase {self.phase} out of range 0-7")
        if self.source_genome_assembly not in ("GRCh37", "GRCh38", "other"):
            raise IncompleteProvenanceError(
                f"assembly {self.source_genome_assembly!r} not GRCh37/GRCh38/other"
            )

    def to_yaml(self) -> str:
        """Emit the YAML frontmatter block in SPEC field order, deterministically."""
        def fmt(value) -> str:
            if isinstance(value, date):
                return value.isoformat()
            if isinstance(value, (tuple, list)):
                return "[" + ", ".join(str(v) for v in value) + "]"
            if value is None:
                return "null"
            return str(value)

        rows = [f"{name}: {fmt(getattr(self, name))}" for name in PROVENANCE_FIELD_ORDER]
        return "---\n" + "\n".join(rows) + "\n---"


@dataclass(frozen=True)
class RemovedClaim:
    """A claim deleted from the superseded doc (SPEC Provenance Summary).

    ``verbatim`` is the exact text removed from the v1 doc; ``source`` is the
    archived filename it came from. The renderer emits these with a
    ``[verbatim from archive: <source>]`` attribution so the blacklist gate
    treats the (necessarily aspirational) quote as exempt verbatim archive data.
    """

    verbatim: str
    reason: str  # one of: unsupported by genome | no allow-list citation | aspirational phrasing | contradicts INDEX
    source: str = ""  # archived filename the quote was removed from


@dataclass(frozen=True)
class Claim:
    """An added analytical claim. A claim without provenance cannot exist.

    Per SPEC Rule 1, an asserted health/PGx claim must trace to an INDEX rsid
    with the subject's genotype (``rsid`` + ``genotype``) AND at least one
    allow-list citation (``citation_keys``). Construction validates that linkage
    so a bare assertion fails fast.
    """

    text: str
    rsid: Optional[str]
    chrom: Optional[str]
    pos: Optional[str]
    genotype: Optional[str]
    citation_keys: tuple[str, ...]
    clinical: bool = True  # whether this is a health/dietary/PGx claim (Rule 1 applies)

    def __post_init__(self) -> None:
        if self.clinical:
            if not self.rsid:
                raise DecoderError(f"clinical claim has no INDEX rsid: {self.text!r} (SPEC Rule 1a)")
            if not self.citation_keys:
                raise DecoderError(
                    f"clinical claim has no allow-list citation: {self.text!r} (SPEC Rule 1b)"
                )

    def summary_line(self) -> str:
        """One-line 'Added claims' entry (SPEC Provenance Summary)."""
        loc = f"{self.chrom}:{self.pos}" if self.chrom and self.pos else ""
        cites = " ".join(f"[{c}]" for c in self.citation_keys)
        return f"- {self.rsid} {loc} {self.genotype} → {self.text} {cites}".strip()


@dataclass(frozen=True)
class Section:
    heading: str
    body_md: str  # markdown body of the section (no heading line)


@dataclass(frozen=True)
class Document:
    """A renderable canonical document. Carrying a Provenance Block is mandatory.

    ``render.write_doc`` is the only sanctioned writer; it builds the
    ``## Provenance Summary`` from ``removed_claims`` / ``added_claims`` and runs
    the blacklist gate before writing.
    """

    path: Path
    provenance: ProvenanceBlock
    title: str
    sections: tuple[Section, ...]
    removed_claims: tuple[RemovedClaim, ...] = ()
    added_claims: tuple[Claim, ...] = ()
    historical_context: str = ""  # plain-text archive references (SPEC Cross-Reference rules)


# --------------------------------------------------------------------------- #
# CLI helpers (mirrors genome-reader's flat-flag parser for a consistent feel)
# --------------------------------------------------------------------------- #


def parse_flat_args(args: list[str], value_flags: set[str], bool_flags: set[str] | None = None):
    """Parse a flat CLI tolerant of positional placement.

    Returns ``(positionals, flags)`` where ``flags`` maps each seen value-flag to
    its argument and each seen bool-flag to ``"true"``. Mirrors genome-reader's
    ``parse_flat_args`` so the two skills feel the same on the command line.
    """
    bool_flags = bool_flags or set()
    flags: dict[str, str] = {}
    positionals: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in value_flags:
            if i + 1 >= len(args):
                die(f"flag {a} requires an argument")
            flags[a] = args[i + 1]
            i += 2
            continue
        if a in bool_flags:
            flags[a] = "true"
            i += 1
            continue
        positionals.append(a)
        i += 1
    return positionals, flags


def parse_snapshot_date(flags: dict[str, str]) -> date:
    """Resolve ``--snapshot-date YYYY-MM-DD``, defaulting to today only if unset.

    The snapshot date is an explicit determinism input (SPEC line 370). Defaulting
    to today is a convenience for interactive use; reproducible reruns always
    pass it explicitly.
    """
    raw = flags.get("--snapshot-date")
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError as e:
            die(f"--snapshot-date must be YYYY-MM-DD: {e}")
    return date.today()


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def die(msg: str, code: int = 2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------- #
# rsid pool extraction (SPEC: markdown grep, NOT a genome-reader operation)
# --------------------------------------------------------------------------- #

_RSID_RE = re.compile(r"\brs[0-9]+\b")


def extract_rsids(text: str) -> list[str]:
    """Every rsid token in a markdown doc, de-duplicated, in first-seen order."""
    seen: dict[str, None] = {}
    for m in _RSID_RE.finditer(text):
        seen.setdefault(m.group(0), None)
    return list(seen)


def iter_archive_docs(archive_dir: str | os.PathLike) -> Iterable[Path]:
    """Every ``*.md`` under the archive, sorted for deterministic ordering."""
    return sorted(Path(archive_dir).rglob("*.md"))


# --------------------------------------------------------------------------- #
# Structured report model  (Workstream D2/D3 — feeds the HelixyAI renderer)
# --------------------------------------------------------------------------- #
#
# These types carry the structured content the HelixyAI templates render
# (provider-alert table, tier-coded finding blocks, genotype table, the index
# doc grid). They are SEPARATE from the markdown-centric ``Document`` above so
# the foundation's legacy render path stays untouched. The renderer
# (``render.py``) maps these to the exact design markup; the rebuild agent
# (Workstream C) populates them later — still gated by ``render.write_*``
# (archive guard + Provenance Summary + blacklist).

Tier = Literal[1, 2, 3]


def tier_class(tier: int) -> str:
    """Map a tier (1/2/3) to the design's ``t1|t2|t3`` class suffix."""
    if tier not in (1, 2, 3):
        raise DecoderError(f"tier must be 1, 2 or 3; got {tier!r}")
    return f"t{tier}"


def evidence_class(level: str) -> str:
    """Map an evidence level to the design's ``.ev`` modifier (a|b|c)."""
    key = level.strip().upper()
    if key.startswith("A") or "LEVEL A" in key:
        return "a"
    if key.startswith("B") or "LEVEL B" in key:
        return "b"
    return "c"  # Level C / Limited / anything else → muted


@dataclass(frozen=True)
class Triple:
    """An rsID + chr:pos + genotype datum → three ``<code class="dna …" data-*>`` chips."""

    rsid: str
    chrom: str
    pos: str
    genotype: str

    def __post_init__(self) -> None:
        if not self.rsid:
            raise DecoderError("Triple requires an rsid (SPEC Rule 1a — INDEX traceability)")

    @property
    def pos_label(self) -> str:
        """``chr:pos`` with a thousands-separated position when numeric."""
        p = str(self.pos)
        return f"{self.chrom}:{int(p):,}" if p.isdigit() else f"{self.chrom}:{p}"


@dataclass(frozen=True)
class Citation:
    """An allow-list citation → ``<a href rel="external" data-access-date>``.

    ``source_key`` MUST be a key in ``allowlist_sources.json`` (SPEC Evidence
    Sources, Rule 1b); validated at construction so an off-list citation cannot
    exist. ``url`` must resolve under that source's ``url_root``.
    """

    source_key: str
    label: str
    url: str
    access_date: str  # YYYY-MM-DD

    def __post_init__(self) -> None:
        allow = load_allowlist()
        if self.source_key not in allow:
            raise AllowlistError(
                f"citation source {self.source_key!r} not in allow-list "
                f"({', '.join(sorted(k for k in allow if not k.startswith('_')))})"
            )
        root = allow[self.source_key].get("url_root", "")
        if root and not self.url.startswith(root):
            raise AllowlistError(
                f"citation url {self.url!r} is not under the {self.source_key!r} "
                f"root {root!r}"
            )


@dataclass(frozen=True)
class Finding:
    """A tier-coded per-gene finding (one ``.finding`` block).

    A clinical finding MUST carry at least one ``Triple`` (rsid → INDEX, Rule 1a)
    and at least one ``Citation`` (allow-list, Rule 1b). ``historical_note`` is
    rendered in a de-emphasized ``blockquote.hist`` and is emitted WITH the
    ``[verbatim from archive…]`` attribution so the blacklist gate exempts it.
    """

    gene: str
    name: str
    tier: int
    evidence: str  # display label e.g. "CPIC Level A" / "Limited"
    triples: tuple[Triple, ...]
    implication: str
    citations: tuple[Citation, ...]
    subtitle: str = ""
    historical_note: str = ""

    def __post_init__(self) -> None:
        if self.tier not in (1, 2, 3):
            raise DecoderError(f"Finding.tier must be 1/2/3; got {self.tier!r}")
        if not self.triples:
            raise DecoderError(f"clinical finding {self.gene!r} has no rsid Triple (SPEC Rule 1a)")
        if not self.citations:
            raise DecoderError(f"clinical finding {self.gene!r} has no allow-list citation (SPEC Rule 1b)")


@dataclass(frozen=True)
class AlertRow:
    """One row of the provider-ready alert table (CPIC-graded actionable finding)."""

    drug: str
    gene_genotype: str  # e.g. "GENE1 *2/*2 (rs0000001 AG)"
    evidence: str  # display label e.g. "CPIC Level A"
    recommendation: str
    citation: Citation

    def __post_init__(self) -> None:
        if not self.recommendation:
            raise DecoderError("AlertRow requires a recommendation")


@dataclass(frozen=True)
class GenotypeRow:
    """One row of the per-document genotype table."""

    triple: Triple
    gene: str
    tier: int

    def __post_init__(self) -> None:
        if self.tier not in (1, 2, 3):
            raise DecoderError(f"GenotypeRow.tier must be 1/2/3; got {self.tier!r}")


@dataclass(frozen=True)
class ReportDocument:
    """A structured analysis document the HelixyAI ``document.html`` renders.

    Carries the Provenance Block (card + meta + Rule 6) and the structured body
    (alert rows, findings, genotype rows). Separate from the markdown-centric
    ``Document`` so the foundation's legacy path is untouched.
    """

    doc_id: str
    title: str
    group: str
    provenance: ProvenanceBlock
    kicker: str = ""
    subtitle: str = ""
    facts: tuple[str, ...] = ()
    alert_rows: tuple[AlertRow, ...] = ()
    findings: tuple[Finding, ...] = ()
    genotype_rows: tuple[GenotypeRow, ...] = ()

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise IncompleteProvenanceError("ReportDocument requires a title")


@dataclass(frozen=True)
class ReportDoc:
    """One entry in the index/sidebar doc set (a card + a nav link)."""

    doc_id: str
    title: str
    filename: str  # relative href, e.g. "Pharmacogenomics Analysis.html"
    group: str
    number: str  # ordinal label e.g. "04"
    blurb: str = ""
    tier_summary: str = ""  # e.g. "2 Tier 1"; "" = none
    tier: int = 0  # 1 => card carries .t1 + data-tier="t1"; 0 => none
    findings_label: str = ""  # e.g. "5 findings" / "pipeline"
    available: bool = False
    search_terms: str = ""
    icon_token: str = "NODE"  # one of the template's ICON_* keys


@dataclass(frozen=True)
class ReportManifest:
    """The whole report: the ordered doc set + report-level provenance + stats.

    Single source the index generator AND each per-document nav (sidebar /
    breadcrumb / pager) consume, so cross-links and the grid stay consistent.
    """

    subject_label: str
    report_id: str
    assembly: str
    array: str
    access_date: str
    sources: tuple[str, ...]
    source_sha256: str
    supersedes: str
    supersedes_sha256: str
    docs: tuple[ReportDoc, ...]
    groups: tuple[str, ...]
    stats: dict  # {documents, variants_reviewed, tier1, cpic_a, carriers}
    build_label: str = "genome-decoder"

    def docs_in_group(self, group: str) -> list["ReportDoc"]:
        return [d for d in self.docs if d.group == group]

    def doc_index(self, doc_id: str) -> int:
        for i, d in enumerate(self.docs):
            if d.doc_id == doc_id:
                return i
        return -1
