"""Detection engine: pair freshness (L1) + anchors (L2) + completeness gates.

Pair states:
  GREEN      both sides match the last ack — coherent
  AMBER      both sides moved, but every code-touching commit also touched
             the doc (co-movement) — provisionally coherent, unconfirmed
  DOC_STALE  code moved, doc did not — the doc likely lags the code
  CODE_LAG   doc moved, code did not — the code likely lags the spec
  BROKEN     both moved in commits that did not travel together
  UNACKED    no (readable) ack exists for this pair yet

The state machine never guesses which side is *wrong* — that judgement is the
ack. An in-commit `Staledocs-Ack: <doc-path|all>` trailer moves the baseline
forward the same way an explicit `staledocs ack` does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import anchors as anchors_mod
from . import gitio, ledger
from .anchors import AnchorFinding, CodeIndex
from .config import Config
from .mapping import MappingResult, ResolvedPair

GREEN = "GREEN"
AMBER = "AMBER"
DOC_STALE = "DOC_STALE"
CODE_LAG = "CODE_LAG"
BROKEN = "BROKEN"
UNACKED = "UNACKED"

RED_STATES = {DOC_STALE, CODE_LAG, BROKEN, UNACKED}


@dataclass
class AnchorHit:
    """One piece of intersection evidence: the doc names this thing, and the
    change touched it."""

    file: str
    token: str
    kind: str  # "path" (file granularity) | "ident" (line granularity)
    doc_lines: list[int] = field(default_factory=list)
    changed_lines: list[str] = field(default_factory=list)


@dataclass
class PairReport:
    doc: str
    state: str
    origin: str
    code_files: list[str]
    changed_code: list[str] = field(default_factory=list)
    doc_changed: bool = False
    added_code: list[str] = field(default_factory=list)
    removed_code: list[str] = field(default_factory=list)
    rename_hints: dict[str, str] = field(default_factory=dict)
    ack_commit: str | None = None
    ack_at: str = ""
    detail: str = ""
    mentioned_changed: list[str] = field(default_factory=list)
    hit_anchors: list[AnchorHit] = field(default_factory=list)


@dataclass
class CheckResult:
    pairs: list[PairReport] = field(default_factory=list)
    anchor_findings: list[AnchorFinding] = field(default_factory=list)
    unclassified_docs: list[str] = field(default_factory=list)
    orphan_pairs: list[str] = field(default_factory=list)
    uncovered_source: list[str] = field(default_factory=list)
    dead_pair_docs: list[str] = field(default_factory=list)
    out_of_scope_pair_code: list[str] = field(default_factory=list)
    stale_ledger_docs: list[str] = field(default_factory=list)
    config_weakenings: list[str] = field(default_factory=list)
    config_baseline_missing: bool = False
    examples: object | None = None  # ExamplesReport when the layer is on

    def red_count(self) -> int:
        return (
            sum(1 for p in self.pairs if p.state in RED_STATES)
            + len(self.anchor_findings)
            + len(self.unclassified_docs)
            + len(self.orphan_pairs)
            + len(self.uncovered_source)
            + len(self.dead_pair_docs)
            + len(self.out_of_scope_pair_code)
            + len(self.config_weakenings)
        )

    def amber_count(self) -> int:
        return sum(1 for p in self.pairs if p.state == AMBER)


def _effective_ack(
    repo_root: Path, pair: ResolvedPair, ack: ledger.Ack
) -> tuple[ledger.Ack, str | None]:
    """Advance the ack baseline through any `Staledocs-Ack` trailers.

    Returns the effective ack plus the commit sha it was absorbed from (for
    reporting), or the original ack unchanged.

    When the recorded commit is unknown to this clone (acked on a branch tip
    that a squash merge later discarded, or lost to a shallow fetch), the
    trailer scan falls back to the full history instead of going blind —
    otherwise every such pair reads BROKEN on CI while local checks pass.
    """
    since: str | None = ack.commit
    if since is not None and not gitio.commit_exists(repo_root, since):
        since = None
    absorbed_from: str | None = None
    effective = ack
    for commit in gitio.commits_since(repo_root, since):
        if commit.sha == gitio.WORKTREE:
            continue
        if not commit.trailer_acks:
            continue
        if "all" in commit.trailer_acks or pair.doc in commit.trailer_acks:
            doc_blob = gitio.blob_at_commit(repo_root, commit.sha, pair.doc)
            if doc_blob is None:
                continue
            code_blobs: dict[str, str] = {}
            for rel in pair.code_files:
                blob = gitio.blob_at_commit(repo_root, commit.sha, rel)
                if blob is not None:
                    code_blobs[rel] = blob
            effective = ledger.Ack(
                commit=commit.sha,
                doc_blob=doc_blob,
                code_blobs=code_blobs,
                at=effective.at,
                note=f"trailer ack @ {commit.sha[:10]}",
            )
            absorbed_from = commit.sha
    return effective, absorbed_from


def _co_moved(repo_root: Path, ack_commit: str | None, doc: str, changed_code: set[str]) -> bool:
    """True when every commit (or the dirty worktree) that touched the changed
    code also touched the doc — the amber co-movement rule."""
    if ack_commit is None or not gitio.commit_exists(repo_root, ack_commit):
        return False
    saw_code_change = False
    for commit in gitio.commits_since(repo_root, ack_commit):
        touched_code = commit.files & changed_code
        if not touched_code:
            continue
        saw_code_change = True
        if doc not in commit.files:
            return False
    return saw_code_change


@dataclass
class MentionContext:
    """Precomputed repo facts for the anchor-weighted L1 (shared per run)."""

    anchors_rule: object
    all_files: set[str]
    all_dirs: set[str]
    path_roots: list[str]


_SNIPPET_LIMIT = 3  # changed-line snippets kept per hit (evidence, not a dump)
_SNIPPET_WIDTH = 160


def _changed_line_text(repo_root: Path, rel: str, old_blob: str | None) -> list[str]:
    """Added/removed line text for one file between the acked blob and now.

    When the old blob is unknown to git (ack taken on a dirty worktree that
    was never committed), the whole current content counts as changed —
    conservative in the red direction, never silently green.
    """
    new_text: str | None
    try:
        new_text = (repo_root / rel).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        new_text = None
    old_text = gitio.blob_text(repo_root, old_blob) if old_blob else None
    return gitio.changed_lines(old_text, new_text)


def _intersect(
    repo_root: Path,
    pair: ResolvedPair,
    changed: set[str],
    ack: ledger.Ack,
    ctx: MentionContext,
) -> tuple[list[AnchorHit], int]:
    """The anchor-graded L1 core: intersect the doc's mentions with the diff.

    - a path anchor resolving to a changed file hits at file granularity
      (the doc talks about the file as a unit)
    - an identifier anchor hits at line granularity: only when the token
      appears in the added/removed lines since the ack
    Returns (hits, total_anchor_count).
    """
    mentions = anchors_mod.doc_mention_index(
        repo_root, pair.doc, ctx.anchors_rule, ctx.all_files, ctx.all_dirs, ctx.path_roots
    )
    hits: list[AnchorHit] = []
    for rel in sorted(changed):
        if rel in mentions.path_files:
            hits.append(
                AnchorHit(
                    file=rel,
                    token=rel,
                    kind="path",
                    doc_lines=sorted(set(mentions.path_files[rel])),
                )
            )
    if mentions.idents:
        path_hit_files = {h.file for h in hits}
        for rel in sorted(changed - path_hit_files):
            lines = _changed_line_text(repo_root, rel, ack.code_blobs.get(rel))
            if not lines:
                continue
            for token, doc_lines in sorted(mentions.idents.items()):
                matched = [ln for ln in lines if token in ln]
                if not matched:
                    continue
                hits.append(
                    AnchorHit(
                        file=rel,
                        token=token,
                        kind="ident",
                        doc_lines=sorted(set(doc_lines)),
                        changed_lines=[
                            ln.strip()[:_SNIPPET_WIDTH] for ln in matched[:_SNIPPET_LIMIT]
                        ],
                    )
                )
    return hits, mentions.total_anchors


def make_mention_ctx(repo_root: Path, cfg: Config) -> MentionContext:
    tracked = set(gitio.ls_files(repo_root))
    return MentionContext(
        anchors_rule=cfg.anchors,
        all_files=tracked,
        all_dirs=anchors_mod.dirs_of(tracked),
        path_roots=cfg.anchors.path_roots,
    )


def check_pair(
    repo_root: Path,
    pair: ResolvedPair,
    mention_ctx: MentionContext | None = None,
) -> PairReport:
    report = PairReport(
        doc=pair.doc,
        state=UNACKED,
        origin=pair.origin,
        code_files=pair.code_files,
    )
    ack = ledger.read_ack(repo_root, pair.doc)
    if ack is None:
        report.detail = "no ack recorded (or ledger entry unreadable — fail-safe)"
        return report

    ack, absorbed = _effective_ack(repo_root, pair, ack)
    report.ack_commit = ack.commit
    report.ack_at = ack.at
    if absorbed:
        report.detail = f"baseline advanced by trailer ack in {absorbed[:10]}"

    doc_blob_now = gitio.hash_object(repo_root, pair.doc)
    report.doc_changed = doc_blob_now != ack.doc_blob

    current_code = set(pair.code_files)
    acked_code = set(ack.code_blobs)
    report.added_code = sorted(current_code - acked_code)
    report.removed_code = sorted(acked_code - current_code)

    changed: set[str] = set(report.added_code)
    current_blobs: dict[str, str] = {}
    for rel in sorted(current_code & acked_code):
        blob = gitio.hash_object(repo_root, rel)
        current_blobs[rel] = blob or ""
        if blob != ack.code_blobs[rel]:
            changed.add(rel)
    changed.update(report.removed_code)
    report.changed_code = sorted(changed)

    # rename hint: a removed file whose acked blob now lives elsewhere
    if report.removed_code and report.added_code:
        added_blobs = {rel: gitio.hash_object(repo_root, rel) for rel in report.added_code}
        for removed in report.removed_code:
            old_blob = ack.code_blobs.get(removed)
            for added, blob in added_blobs.items():
                if blob is not None and blob == old_blob:
                    report.rename_hints[removed] = added
                    break

    code_changed = bool(changed)
    if not code_changed and not report.doc_changed:
        report.state = GREEN
    elif code_changed and not report.doc_changed:
        # anchor-graded L1 (v0.2): the break is RED only when the change
        # touches something this doc names — a path anchor's file moved, or a
        # quoted identifier appears in the added/removed lines. Unrelated
        # churn inside a wide pair downgrades to AMBER, so RED keeps its
        # urgency and the reflexive-ack habit loses its fuel. A doc with no
        # anchors at all gives the grader nothing — it stays RED by rule.
        if mention_ctx is None:
            report.state = DOC_STALE
        else:
            hits, total_anchors = _intersect(repo_root, pair, changed, ack, mention_ctx)
            report.hit_anchors = hits
            report.mentioned_changed = sorted({h.file for h in hits})
            if total_anchors == 0:
                report.state = DOC_STALE
                report.detail = "doc has no anchors — ungradeable, red by rule"
            elif hits:
                report.state = DOC_STALE
            else:
                report.state = AMBER
                report.detail = (
                    f"{len(changed)} file(s) moved, none referenced by this doc"
                )
    elif report.doc_changed and not code_changed:
        report.state = CODE_LAG
    else:
        if _co_moved(repo_root, ack.commit, pair.doc, changed):
            report.state = AMBER
        else:
            report.state = BROKEN
    return report


def run_check(repo_root: Path, cfg: Config, mapping: MappingResult) -> CheckResult:
    result = CheckResult(
        unclassified_docs=mapping.unclassified_docs,
        orphan_pairs=mapping.orphan_pairs,
        uncovered_source=mapping.uncovered_source,
        dead_pair_docs=mapping.dead_pair_docs,
        out_of_scope_pair_code=mapping.out_of_scope_pair_code,
    )

    # executable-docs layer (opt-in, warn-only — the semantic layer never
    # blocks a commit; that right belongs to the structural layer alone)
    if cfg.examples:
        from . import examples as examples_mod

        result.examples = examples_mod.build(
            repo_root, cfg.examples, list(mapping.doc_files)
        )

    # config weakening (the backdoor check): red until accepted via ack --config
    baseline = ledger.read_config_ack(repo_root)
    if baseline is None:
        result.config_baseline_missing = True
    else:
        result.config_weakenings = ledger.config_weakenings(
            baseline, ledger.config_snapshot(cfg)
        )

    mention_ctx = make_mention_ctx(repo_root, cfg)
    for pair in mapping.pairs:
        result.pairs.append(check_pair(repo_root, pair, mention_ctx))

    # ledger entries whose doc vanished from the mapping (deleted or renamed)
    mapped_docs = {p.doc for p in mapping.pairs}
    result.stale_ledger_docs = sorted(
        d for d in ledger.known_docs(repo_root) if d not in mapped_docs
    )

    # anchors (L2)
    all_files = set(mapping.source_files) | set(mapping.doc_files)
    tracked = set(gitio.ls_files(repo_root))
    all_dirs = anchors_mod.dirs_of(tracked)
    repo_index = CodeIndex(repo_root, sorted(mapping.source_files))

    def check_ignored(cands: list[str]) -> set[str]:
        return gitio.ignored_paths(repo_root, cands)

    def _doc_anchors(doc: str, pair_files: list[str] | None) -> None:
        try:
            text = (repo_root / doc).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return
        found = anchors_mod.extract(doc, text, cfg.anchors)
        if not found:
            return
        pair_index = CodeIndex(repo_root, pair_files) if pair_files is not None else None
        result.anchor_findings.extend(
            anchors_mod.verify(
                repo_root,
                doc,
                found,
                pair_index,
                repo_index,
                tracked,
                all_dirs,
                cfg.anchors.path_roots,
                check_ignored,
            )
        )

    for pair in mapping.pairs:
        _doc_anchors(pair.doc, pair.code_files)
    for doc in mapping.global_docs:
        _doc_anchors(doc, None)
    for doc in mapping.standalone_docs:
        # standalone docs have no code side; only path-like anchors apply,
        # which verify repo-wide inside anchors.verify via the empty index
        try:
            text = (repo_root / doc).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found = [a for a in anchors_mod.extract(doc, text, cfg.anchors) if a.path_like]
        if found:
            result.anchor_findings.extend(
                anchors_mod.verify(
                    repo_root,
                    doc,
                    found,
                    None,
                    repo_index,
                    tracked,
                    all_dirs,
                    cfg.anchors.path_roots,
                    check_ignored,
                )
            )

    _ = all_files  # reserved for future scope tuning
    return result


def pair_fingerprint(repo_root: Path, pair: ResolvedPair) -> str:
    """Deterministic token over the pair's current content.

    The two-step ack echoes this back: if either side moves between showing
    the evidence and confirming, the token no longer matches and the confirm
    is refused — the evidence shown is always the evidence acked.
    """
    import hashlib

    parts = [pair.doc, gitio.hash_object(repo_root, pair.doc) or "-"]
    for rel in pair.code_files:
        parts.append(f"{rel}:{gitio.hash_object(repo_root, rel) or '-'}")
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def aggregate_token(fingerprints: list[str]) -> str:
    import hashlib

    if len(fingerprints) == 1:
        return fingerprints[0]
    return hashlib.sha1("\n".join(sorted(fingerprints)).encode("utf-8")).hexdigest()[:12]


def build_evidence(repo_root: Path, report: PairReport) -> dict:
    """The read-this-before-you-stamp block for one broken pair (JSON-ready).

    Pairs the doc's own words with the change: every hit carries the doc
    line text alongside the changed-line snippets, so the reader (human or
    agent) gets the exact two things to compare, not a file list.
    """
    import contextlib

    doc_lines: list[str] = []
    with contextlib.suppress(OSError):
        doc_lines = (repo_root / report.doc).read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines()

    def _excerpt(lineno: int) -> str:
        if 1 <= lineno <= len(doc_lines):
            return doc_lines[lineno - 1].strip()[:_SNIPPET_WIDTH]
        return ""

    hits = [
        {
            "file": h.file,
            "token": h.token,
            "kind": h.kind,
            "doc_lines": [
                {"line": ln, "text": _excerpt(ln)} for ln in h.doc_lines[:_SNIPPET_LIMIT]
            ],
            "changed_lines": h.changed_lines,
        }
        for h in report.hit_anchors
    ]
    return {
        "doc": report.doc,
        "state": report.state,
        "changed_code": report.changed_code,
        "added_code": report.added_code,
        "removed_code": report.removed_code,
        "rename_hints": report.rename_hints,
        "doc_changed": report.doc_changed,
        "detail": report.detail,
        "hits": hits,
    }


def note_references_evidence(note: str, report: PairReport) -> bool:
    """Deterministic note-content check: the note must name something the
    evidence showed — a changed file (path or basename), a hit anchor token,
    or the doc itself. A rubber-stamp note fails; no semantic judgement."""
    text = note.strip()
    if not text:
        return False
    candidates: set[str] = set()
    for rel in report.changed_code:
        candidates.add(rel)
        candidates.add(rel.rsplit("/", 1)[-1])
    for h in report.hit_anchors:
        candidates.add(h.token)
    candidates.add(report.doc)
    candidates.add(report.doc.rsplit("/", 1)[-1])
    return any(c and c in text for c in candidates)


def ack_pair(repo_root: Path, pair: ResolvedPair, note: str = "") -> Path:
    doc_blob = gitio.hash_object(repo_root, pair.doc)
    if doc_blob is None:
        raise FileNotFoundError(f"doc not found: {pair.doc}")
    code_blobs: dict[str, str] = {}
    for rel in pair.code_files:
        blob = gitio.hash_object(repo_root, rel)
        if blob is not None:
            code_blobs[rel] = blob
    return ledger.write_ack(
        repo_root,
        pair.doc,
        commit=gitio.head_commit(repo_root),
        doc_blob=doc_blob,
        code_blobs=code_blobs,
        note=note,
    )
