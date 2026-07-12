"""Rendering: human-readable CLI output and the machine-readable JSON contract.

The JSON shape is the agent-facing API — AI agents consume it to decide what
to fix. Treat every key as a compatibility surface.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict

from . import __version__
from .engine import AMBER, GREEN, RED_STATES, CheckResult
from .mapping import MappingResult

_STATE_ICON = {
    GREEN: "ok",
    AMBER: "~ ",
    "DOC_STALE": "!!",
    "CODE_LAG": "!!",
    "BROKEN": "!!",
    "UNACKED": "??",
}


def _color(enabled: bool, code: str, text: str) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def render_human(result: CheckResult, show_green: bool = False, color: bool | None = None) -> str:
    if color is None:
        color = sys.stdout.isatty()
    red = lambda t: _color(color, "31", t)  # noqa: E731
    yellow = lambda t: _color(color, "33", t)  # noqa: E731
    green = lambda t: _color(color, "32", t)  # noqa: E731
    dim = lambda t: _color(color, "2", t)  # noqa: E731

    lines: list[str] = []

    for doc in result.dead_pair_docs:
        lines.append(red(f"[mapping] pair doc does not exist: {doc}"))
    for doc in result.unclassified_docs:
        lines.append(
            red(f"[coverage] doc not classified (pair it, or declare standalone/global): {doc}")
        )
    for doc in result.orphan_pairs:
        lines.append(red(f"[coverage] pair matches no code (orphan doc): {doc}"))
    for src in result.uncovered_source:
        lines.append(red(f"[coverage] source file belongs to no doc: {src}"))
    for doc in result.stale_ledger_docs:
        lines.append(
            yellow(f"[ledger] unmapped entry (clean up with `staledocs ack --prune`): {doc}")
        )

    for pair in result.pairs:
        if pair.state == GREEN and not show_green:
            continue
        icon = _STATE_ICON.get(pair.state, "??")
        paint = green if pair.state == GREEN else yellow if pair.state == AMBER else red
        lines.append(paint(f"[{icon}] {pair.state:<9} {pair.doc}"))
        if pair.state in RED_STATES or pair.state == AMBER:
            if pair.changed_code:
                shown = pair.changed_code[:6]
                more = len(pair.changed_code) - len(shown)
                suffix = f" (+{more} more)" if more > 0 else ""
                lines.append(dim(f"      code moved: {', '.join(shown)}{suffix}"))
            if pair.doc_changed:
                lines.append(dim("      doc moved since last ack"))
            for old, new in pair.rename_hints.items():
                lines.append(dim(f"      rename? {old} -> {new} (identical content)"))
            if pair.detail:
                lines.append(dim(f"      {pair.detail}"))

    for f in result.anchor_findings:
        lines.append(red(f"[anchor] {f.doc}:{f.line} `{f.token}` not found in {f.scope} scope"))

    reds = result.red_count()
    ambers = result.amber_count()
    greens = sum(1 for p in result.pairs if p.state == GREEN)
    summary = f"staledocs: {reds} red, {ambers} amber, {greens} green pairs"
    lines.append((red if reds else yellow if ambers else green)(summary))
    return "\n".join(lines)


def render_json(result: CheckResult, mapping: MappingResult, gate: str) -> str:
    payload = {
        "staledocs": __version__,
        "schema": 1,
        "gate": gate,
        "summary": {
            "red": result.red_count(),
            "amber": result.amber_count(),
            "green": sum(1 for p in result.pairs if p.state == GREEN),
        },
        "pairs": [asdict(p) for p in result.pairs],
        "anchors": [asdict(a) for a in result.anchor_findings],
        "coverage": {
            "unclassified_docs": result.unclassified_docs,
            "orphan_pairs": result.orphan_pairs,
            "uncovered_source": result.uncovered_source,
            "dead_pair_docs": result.dead_pair_docs,
            "stale_ledger_docs": result.stale_ledger_docs,
        },
        "classification": {
            "paired": [p.doc for p in mapping.pairs],
            "standalone": mapping.standalone_docs,
            "global": mapping.global_docs,
        },
    }
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"
