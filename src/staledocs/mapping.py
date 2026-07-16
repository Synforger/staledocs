"""Resolve the config into a concrete classification of every file.

Outputs:
  - pairs: doc -> resolved code files (explicit rules first, then mirror)
  - standalone docs (declared code-less)
  - global docs (anchor-only, no ledger)
  - findings: unclassified docs, orphan pairs, uncovered source files,
    dead mapping entries (pair doc that does not exist)

The completeness gate lives here: every source file must belong to at least
one pair, and every doc must be classified. Silence is never coverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import globs
from .config import Config, PairRule


@dataclass
class ResolvedPair:
    doc: str
    code_patterns: list[str]
    code_files: list[str]
    origin: str  # "explicit" | "mirror"


@dataclass
class MappingResult:
    pairs: list[ResolvedPair] = field(default_factory=list)
    standalone_docs: list[str] = field(default_factory=list)
    global_docs: list[str] = field(default_factory=list)
    unclassified_docs: list[str] = field(default_factory=list)
    orphan_pairs: list[str] = field(default_factory=list)
    uncovered_source: list[str] = field(default_factory=list)
    dead_pair_docs: list[str] = field(default_factory=list)
    glob_pair_no_match: list[str] = field(default_factory=list)
    out_of_scope_pair_code: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    doc_files: list[str] = field(default_factory=list)


def _mirror_candidates(cfg: Config, doc: str) -> list[str]:
    """Glob candidates the mirror convention derives for one doc path."""
    root = cfg.mirror.docs_root
    prefix = root + "/" if root else ""
    if not doc.startswith(prefix):
        return []
    stem = doc[len(prefix):]
    if stem.endswith(".md"):
        stem = stem[: -len(".md")]
    # docs/foo/index.md and docs/foo/_README.md own the folder "foo"
    for marker in ("/index", "/_README", "/README"):
        if stem.endswith(marker):
            stem = stem[: -len(marker)]
            break
    if not stem:
        return []
    out: list[str] = []
    for code_root in cfg.mirror.code_roots:
        out.append(f"{code_root}/{stem}/**")
        out.append(f"{code_root}/{stem}.*")
    return out


def resolve(cfg: Config, all_files: list[str]) -> MappingResult:
    result = MappingResult()

    result.source_files = globs.filter_paths(all_files, cfg.source_include, cfg.source_exclude)
    result.doc_files = globs.filter_paths(all_files, cfg.docs_include, cfg.docs_exclude)
    # a file matching both scopes is a doc, never source: counting it as
    # "uncovered source" too would demand a doc for a doc (double-counted
    # red), while the doc-classification gate already watches it
    doc_set = set(result.doc_files)
    result.source_files = [f for f in result.source_files if f not in doc_set]
    file_set = set(all_files)

    classified: set[str] = set()

    # 1. global docs (README class) — anchors only
    for doc in result.doc_files:
        if globs.match_any(cfg.global_docs, doc):
            result.global_docs.append(doc)
            classified.add(doc)

    # 2. standalone docs — declared code-less, exempt from orphan detection
    for doc in result.doc_files:
        if doc in classified:
            continue
        if globs.match_any(cfg.standalone, doc):
            result.standalone_docs.append(doc)
            classified.add(doc)

    # 3. explicit pairs. The doc side is a literal path (a dead path is a
    # finding) or a glob — a glob expands to one independent pair per
    # matched doc. Exact declarations always win regardless of position;
    # globs pair whatever remains, in declaration order (no ordering
    # footgun: a specific pair is never shadowed by a family glob). The
    # "code" side is any tracked side: source files, or other docs — a doc
    # pairing to an upstream doc is the chained-drift declaration
    # (requirements <-> design <-> code), same ledger, same grading. The
    # doc never pairs to itself (degenerate).
    pairable = sorted(set(result.source_files) | set(result.doc_files))
    pairable_set = set(pairable)

    def _check_out_of_scope(rule: PairRule, self_doc: str | None) -> None:
        # A pattern that matches tracked files but contributes nothing
        # pairable means the pair silently covers less than its author
        # declared — the exact quiet-weakening class this tool exists to
        # surface. Never drop it without a finding.
        for pattern in rule.code:
            tracked_hits = [
                f for f in all_files if f != self_doc and globs.match_any([pattern], f)
            ]
            if tracked_hits and not any(f in pairable_set for f in tracked_hits):
                result.out_of_scope_pair_code.append(f"{rule.doc}: {pattern}")

    def _add_pair(doc: str, rule: PairRule) -> None:
        code_files = [f for f in pairable if f != doc and globs.match_any(rule.code, f)]
        result.pairs.append(
            ResolvedPair(
                doc=doc,
                code_patterns=list(rule.code),
                code_files=sorted(code_files),
                origin="explicit",
            )
        )
        classified.add(doc)
        if not code_files:
            result.orphan_pairs.append(doc)

    literal_rules = [r for r in cfg.pairs if not any(ch in r.doc for ch in "*?[")]
    glob_rules = [r for r in cfg.pairs if any(ch in r.doc for ch in "*?[")]

    for rule in literal_rules:
        if rule.doc not in file_set:
            result.dead_pair_docs.append(rule.doc)
            continue
        _check_out_of_scope(rule, rule.doc)
        _add_pair(rule.doc, rule)

    for rule in glob_rules:
        matches = [
            d
            for d in result.doc_files
            if d not in classified and globs.match_any([rule.doc], d)
        ]
        if not matches:
            # a glob quietly matching nothing is the silent-weakening
            # class again — surface it, never drop it
            result.glob_pair_no_match.append(rule.doc)
            continue
        _check_out_of_scope(rule, None)
        for doc in matches:
            _add_pair(doc, rule)

    # 4. mirror convention for whatever docs remain
    if cfg.mirror.enabled:
        for doc in result.doc_files:
            if doc in classified:
                continue
            candidates = _mirror_candidates(cfg, doc)
            if not candidates:
                continue
            code_files = [f for f in result.source_files if globs.match_any(candidates, f)]
            if code_files:
                result.pairs.append(
                    ResolvedPair(
                        doc=doc,
                        code_patterns=candidates,
                        code_files=sorted(code_files),
                        origin="mirror",
                    )
                )
                classified.add(doc)

    # 5. completeness gates
    result.unclassified_docs = sorted(d for d in result.doc_files if d not in classified)

    covered: set[str] = set()
    for pair in result.pairs:
        covered.update(pair.code_files)
    result.uncovered_source = sorted(f for f in result.source_files if f not in covered)

    result.pairs.sort(key=lambda p: p.doc)
    result.standalone_docs.sort()
    result.global_docs.sort()
    result.orphan_pairs.sort()
    result.dead_pair_docs.sort()
    result.glob_pair_no_match.sort()
    result.out_of_scope_pair_code.sort()
    return result
