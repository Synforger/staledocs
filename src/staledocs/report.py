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
    for pattern in result.glob_pair_no_match:
        lines.append(
            red(
                "[mapping] pair doc glob matches no doc "
                f"(fix the glob, or drop the pair): {pattern}"
            )
        )
    for entry in result.out_of_scope_pair_code:
        lines.append(
            red(
                f"[mapping] pair code entry matches only files outside "
                f"source/docs scope (widen the include, or drop the entry): {entry}"
            )
        )
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
    for w in result.config_weakenings:
        lines.append(
            red(f"[config] check weakened: {w} (accept with `staledocs ack --config -m ...`)")
        )
    if result.config_baseline_missing:
        lines.append(
            yellow(
                "[config] no accepted baseline yet — record it with "
                "`staledocs ack --config -m 'initial baseline'` "
                "(a first record is initialization, not a weakening approval)"
            )
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
            for hit in pair.hit_anchors:
                where = ",".join(str(n) for n in hit.doc_lines)
                if hit.kind == "path":
                    lines.append(dim(f"      doc names this file (doc line {where}): {hit.file}"))
                else:
                    lines.append(
                        dim(f"      doc quotes `{hit.token}` (doc line {where})"
                            f" — changed in {hit.file}")
                    )
            if pair.detail:
                lines.append(dim(f"      {pair.detail}"))

    for f in result.anchor_findings:
        lines.append(red(f"[anchor] {f.doc}:{f.line} `{f.token}` not found in {f.scope} scope"))
        if f.hint:
            lines.append(dim(f"      ({f.hint})"))
    if result.anchor_findings:
        # the map is handed out at the moment of stepping, not buried in docs:
        # a missing anchor is rot, a not-built-yet reference, or prose that
        # accurately records a removal — three different correct moves
        lines.append(
            dim(
                "      (rot -> fix the doc; not built yet -> declare it "
                "`planned:<path>`; prose recording a removal is often accurate "
                "— read the surrounding text before editing. Triage table: "
                "docs/setup)"
            )
        )
    missing = [st.doc for st in result.anchor_statuses if st.baseline_missing]
    if missing:
        # unarmed is never silent coverage: until a doc's claims are recorded
        # at an ack, its anchors gate nothing — say so every run
        lines.append(
            yellow(
                f"[anchors] {len(missing)} doc(s) have no anchor baseline — "
                "their anchors are not gating yet; ack them to arm "
                "(unresolved tokens are listed in --json for one-time review)"
            )
        )
    armed = sum(st.armed for st in result.anchor_statuses)
    unarmed = sum(st.unarmed for st in result.anchor_statuses)
    review = sum(len(st.review) for st in result.anchor_statuses)
    if unarmed:
        shortlist = (
            f"; {review} look like path claims — `staledocs unarmed` to review"
            if review
            else ""
        )
        lines.append(
            dim(
                f"[anchors] {armed} armed claim(s), {unarmed} unarmed token(s) "
                f"(unarmed tokens never gate{shortlist})"
            )
        )
    for f in result.planned_pending:
        lines.append(yellow(f"[planned] {f.doc}:{f.line} `{f.token}` planned, not built yet"))
    for f in result.planned_resolved:
        lines.append(
            yellow(
                f"[planned] {f.doc}:{f.line} `{f.token}` has landed — "
                "remove the planned: marker"
            )
        )

    if result.examples is not None and result.examples.enabled:
        for block in result.examples.undeclared:
            lines.append(
                yellow(
                    f"[examples] {block.doc}:{block.line} fenced `{block.tag}` block "
                    f"not classified — map it to a runner in examples:, or to none"
                )
            )
        if result.examples.wired:
            wired = ", ".join(f"{t} x{n}" for t, n in sorted(result.examples.wired.items()))
            lines.append(dim(f"[examples] runner-wired blocks: {wired}"))

    reds = result.red_count()
    ambers = result.amber_count()
    greens = sum(1 for p in result.pairs if p.state == GREEN)
    summary = f"staledocs: {reds} red, {ambers} amber, {greens} green pairs"
    # always counted, so an accumulating pile of planned markers stays visible
    pending = len(result.planned_pending)
    if pending or result.planned_resolved:
        summary += f", {pending} planned"
    if reds:
        # by class, so a big total is actionable: anchor reds fix docs,
        # coverage reds fix pairing, mapping/config reds fix the config
        parts = ", ".join(
            f"{n} {kind}" for kind, n in result.red_breakdown().items() if n
        )
        summary += f" ({parts})"
    lines.append((red if reds else yellow if ambers else green)(summary))
    return "\n".join(lines)


def render_evidence(evidence: dict, color: bool | None = None) -> str:
    """One pair's read-before-you-stamp block: the doc's words next to the
    change that touched them."""
    if color is None:
        color = sys.stdout.isatty()
    red = lambda t: _color(color, "31", t)  # noqa: E731
    dim = lambda t: _color(color, "2", t)  # noqa: E731
    bold = lambda t: _color(color, "1", t)  # noqa: E731

    lines = [bold(f"{evidence['doc']}  [{evidence['state']}]")]
    if evidence["changed_code"]:
        lines.append(f"  code moved: {', '.join(evidence['changed_code'])}")
    for old, new in evidence.get("rename_hints", {}).items():
        lines.append(f"  rename? {old} -> {new}")
    if evidence.get("doc_changed"):
        lines.append("  doc moved since last ack")
    for hit in evidence["hits"]:
        if hit["kind"] == "path":
            lines.append(red(f"  doc names changed file: {hit['file']}"))
        else:
            lines.append(red(f"  doc quotes `{hit['token']}` — changed in {hit['file']}"))
        for dl in hit["doc_lines"]:
            lines.append(dim(f"    doc  L{dl['line']}: {dl['text']}"))
        for cl in hit["changed_lines"]:
            lines.append(dim(f"    diff       : {cl}"))
    for claim in evidence.get("claims", []):
        if claim["kind"] == "path":
            lines.append(red(f"  doc claims file: {claim['file']}"))
        else:
            lines.append(red(f"  doc claims `{claim['token']}`"))
        for dl in claim["doc_lines"]:
            lines.append(dim(f"    doc  L{dl['line']}: {dl['text']}"))
    if not evidence["hits"] and evidence.get("detail"):
        lines.append(dim(f"  {evidence['detail']}"))
    return "\n".join(lines)


def render_json(result: CheckResult, mapping: MappingResult, gate: str) -> str:
    payload = {
        "staledocs": __version__,
        # 2 = baseline-resolved anchors: skipped_tokens removed, anchor_status
        # added, anchor reds mean an armed claim stopped resolving
        "schema": 2,
        "gate": gate,
        "summary": {
            "red": result.red_count(),
            "red_breakdown": result.red_breakdown(),
            "amber": result.amber_count(),
            "green": sum(1 for p in result.pairs if p.state == GREEN),
            "planned": len(result.planned_pending),
        },
        "pairs": [asdict(p) for p in result.pairs],
        "anchors": [asdict(a) for a in result.anchor_findings],
        "planned": {
            "pending": [asdict(a) for a in result.planned_pending],
            "resolved": [asdict(a) for a in result.planned_resolved],
        },
        "anchor_status": {
            "baseline_missing": [
                st.doc for st in result.anchor_statuses if st.baseline_missing
            ],
            "per_doc": {
                st.doc: {
                    "armed": st.armed,
                    "unarmed": st.unarmed,
                    "unarmed_tokens": st.unarmed_tokens,
                    "review_candidates": [
                        {"line": f.line, "token": f.token} for f in st.review
                    ],
                }
                for st in result.anchor_statuses
                if st.armed or st.unarmed
            },
        },
        "coverage": {
            "unclassified_docs": result.unclassified_docs,
            "orphan_pairs": result.orphan_pairs,
            "uncovered_source": result.uncovered_source,
            "dead_pair_docs": result.dead_pair_docs,
            "glob_pair_no_match": result.glob_pair_no_match,
            "out_of_scope_pair_code": result.out_of_scope_pair_code,
            "stale_ledger_docs": result.stale_ledger_docs,
        },
        "config": {
            "weakenings": result.config_weakenings,
            "baseline_missing": result.config_baseline_missing,
        },
        "examples": (
            None
            if result.examples is None or not result.examples.enabled
            else {
                "wired": result.examples.wired,
                "per_doc": result.examples.per_doc,
                "undeclared": [asdict(b) for b in result.examples.undeclared],
            }
        ),
        "classification": {
            "paired": [p.doc for p in mapping.pairs],
            "standalone": mapping.standalone_docs,
            "global": mapping.global_docs,
        },
    }
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"
