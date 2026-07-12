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


@dataclass
class CheckResult:
    pairs: list[PairReport] = field(default_factory=list)
    anchor_findings: list[AnchorFinding] = field(default_factory=list)
    unclassified_docs: list[str] = field(default_factory=list)
    orphan_pairs: list[str] = field(default_factory=list)
    uncovered_source: list[str] = field(default_factory=list)
    dead_pair_docs: list[str] = field(default_factory=list)
    stale_ledger_docs: list[str] = field(default_factory=list)

    def red_count(self) -> int:
        return (
            sum(1 for p in self.pairs if p.state in RED_STATES)
            + len(self.anchor_findings)
            + len(self.unclassified_docs)
            + len(self.orphan_pairs)
            + len(self.uncovered_source)
            + len(self.dead_pair_docs)
        )

    def amber_count(self) -> int:
        return sum(1 for p in self.pairs if p.state == AMBER)


def _effective_ack(
    repo_root: Path, pair: ResolvedPair, ack: ledger.Ack
) -> tuple[ledger.Ack, str | None]:
    """Advance the ack baseline through any `Staledocs-Ack` trailers.

    Returns the effective ack plus the commit sha it was absorbed from (for
    reporting), or the original ack unchanged.
    """
    if ack.commit is None or not gitio.commit_exists(repo_root, ack.commit):
        return ack, None
    absorbed_from: str | None = None
    effective = ack
    for commit in gitio.commits_since(repo_root, ack.commit):
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


def check_pair(repo_root: Path, pair: ResolvedPair) -> PairReport:
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
        report.state = DOC_STALE
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
    )

    for pair in mapping.pairs:
        result.pairs.append(check_pair(repo_root, pair))

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
                )
            )

    _ = all_files  # reserved for future scope tuning
    return result


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
