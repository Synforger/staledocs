"""Executable-docs layer: inventory fenced example blocks, check the wiring.

The one deterministic escape from the semantic-lie limitation is making doc
claims executable — doctest-style examples that a test runner (pytest,
Sybil, byexample) runs on every CI pass. staledocs never executes anything
(non-goal); this layer only keeps the *declaration* honest: the config maps
each fence tag to the runner that executes it (or to `none` — "display
only, not a claim"), and every example block whose tag is undeclared is a
yellow finding until someone classifies it. Declare-by-human,
catch-the-forgetting-by-machine — the same shape as the coverage gate.

Opt-in: no `examples:` section in the config means this layer is silent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_FENCE_OPEN_RE = re.compile(r"^\s*(```+|~~~+)\s*([A-Za-z0-9_+.-]*)")


@dataclass
class ExampleBlock:
    doc: str
    line: int  # 1-indexed opening-fence line
    tag: str


@dataclass
class ExamplesReport:
    enabled: bool = False
    # tag -> block count across all docs, for declared (runner-mapped) tags
    wired: dict[str, int] = field(default_factory=dict)
    # undeclared tags: blocks that are neither runner-mapped nor `none`
    undeclared: list[ExampleBlock] = field(default_factory=list)
    # doc -> count of runner-mapped blocks (health / JSON detail)
    per_doc: dict[str, int] = field(default_factory=dict)


def scan_doc(doc: str, text: str) -> list[ExampleBlock]:
    """Every fenced block with a non-empty info tag, with its opening line."""
    blocks: list[ExampleBlock] = []
    in_fence = False
    fence_marker = ""
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = _FENCE_OPEN_RE.match(line)
        if not m:
            continue
        marker = m.group(1)[0] * 3  # normalize ``` / ~~~ family
        if not in_fence:
            in_fence = True
            fence_marker = marker
            tag = m.group(2).strip().lower()
            if tag:
                blocks.append(ExampleBlock(doc=doc, line=lineno, tag=tag))
        elif line.strip().startswith(fence_marker):
            in_fence = False
    return blocks


def build(
    repo_root: Path,
    runners: dict[str, str | None],
    doc_files: list[str],
) -> ExamplesReport:
    report = ExamplesReport(enabled=bool(runners))
    if not report.enabled:
        return report
    for doc in doc_files:
        try:
            text = (repo_root / doc).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for block in scan_doc(doc, text):
            if block.tag not in runners:
                report.undeclared.append(block)
                continue
            if runners[block.tag] is None:  # declared display-only
                continue
            report.wired[block.tag] = report.wired.get(block.tag, 0) + 1
            report.per_doc[doc] = report.per_doc.get(doc, 0) + 1
    return report
