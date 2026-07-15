"""Pair suggestion from the docs' own anchors (`staledocs init --suggest`).

Docs already declare what they are about — every backticked path and
identifier is a claim of ownership. Resolving those anchors against the
tree yields a pair proposal without asking the user to hand-write globs:
the heaviest part of onboarding becomes review-and-paste instead of
write-from-scratch. Deterministic (anchor extraction + grep), proposal
only — nothing here writes config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import anchors as anchors_mod
from . import globs
from .config import Config


@dataclass
class Suggestion:
    doc: str
    patterns: list[str] = field(default_factory=list)  # empty -> standalone candidate
    via_paths: int = 0
    via_idents: int = 0


def _globify(files: set[str], all_files: set[str]) -> list[str]:
    """Collapse mentioned files into dir globs where the mention dominates.

    A directory becomes `dir/**` only when every tracked file under it was
    mentioned — a clean-ownership signal, not a guess. Anything else stays
    a literal path, so the proposal never claims more than the doc did.
    """
    by_dir: dict[str, set[str]] = {}
    for f in files:
        d = f.rsplit("/", 1)[0] if "/" in f else ""
        by_dir.setdefault(d, set()).add(f)
    out: list[str] = []
    for d, members in sorted(by_dir.items()):
        if d:
            tracked_here = {f for f in all_files if f.rsplit("/", 1)[0] == d}
            if members == tracked_here and len(members) > 1:
                out.append(f"{d}/**")
                continue
        out.extend(sorted(members))
    return out


def build(repo_root: Path, cfg: Config, tracked: list[str]) -> list[Suggestion]:
    doc_files = globs.filter_paths(tracked, cfg.docs_include, cfg.docs_exclude)
    if cfg.source_include:
        source_files = globs.filter_paths(tracked, cfg.source_include, cfg.source_exclude)
    else:
        doc_set = set(doc_files)
        source_files = [f for f in tracked if f not in doc_set]

    all_files = set(tracked)
    all_dirs = anchors_mod.dirs_of(all_files)
    source_set = set(source_files)

    # one pass over the sources: which files contain which doc's identifiers
    per_doc: dict[str, anchors_mod.DocMentions] = {}
    every_ident: set[str] = set()
    for doc in doc_files:
        mentions = anchors_mod.doc_mention_index(
            repo_root, doc, cfg.anchors, all_files, all_dirs, cfg.anchors.path_roots
        )
        per_doc[doc] = mentions
        every_ident.update(mentions.idents)

    containing: dict[str, set[str]] = {tok: set() for tok in every_ident}
    if every_ident:
        for rel in source_files:
            try:
                text = (repo_root / rel).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for tok in every_ident:
                if tok in text:
                    containing[tok].add(rel)

    suggestions: list[Suggestion] = []
    for doc in doc_files:
        mentions = per_doc[doc]
        via_paths = {f for f in mentions.path_files if f in source_set}
        via_idents: set[str] = set()
        for tok in mentions.idents:
            via_idents.update(containing.get(tok, ()))
        via_idents -= via_paths
        mentioned = via_paths | via_idents
        suggestions.append(
            Suggestion(
                doc=doc,
                patterns=_globify(mentioned, all_files) if mentioned else [],
                via_paths=len(via_paths),
                via_idents=len(via_idents),
            )
        )
    return suggestions


def render(suggestions: list[Suggestion]) -> str:
    """A paste-ready YAML fragment plus the reasoning, human-reviewable."""
    lines = [
        "# staledocs pair suggestions — derived from each doc's own anchors.",
        "# Review before pasting: the tool proposes, the human declares.",
        "pairs:",
    ]
    standalone: list[str] = []
    for s in suggestions:
        if not s.patterns:
            standalone.append(s.doc)
            continue
        lines.append(f"  - doc: {s.doc}")
        lines.append(
            "    code: ["
            + ", ".join(f'"{p}"' for p in s.patterns)
            + f"]   # {s.via_paths} path + {s.via_idents} ident anchor(s)"
        )
    if standalone:
        lines.append("")
        lines.append("# no anchors resolved to source — standalone candidates (or global):")
        lines.append("standalone:")
        for d in standalone:
            lines.append(f"  - {d}")
    return "\n".join(lines)
