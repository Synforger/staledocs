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
from .config import Config


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

    # 3. explicit pairs (doc is a literal path; a dead path is a finding)
    for rule in cfg.pairs:
        if rule.doc not in file_set:
            result.dead_pair_docs.append(rule.doc)
            continue
        code_files = [f for f in result.source_files if globs.match_any(rule.code, f)]
        result.pairs.append(
            ResolvedPair(
                doc=rule.doc,
                code_patterns=list(rule.code),
                code_files=sorted(code_files),
                origin="explicit",
            )
        )
        classified.add(rule.doc)
        if not code_files:
            result.orphan_pairs.append(rule.doc)

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
    return result
