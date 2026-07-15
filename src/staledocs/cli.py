"""staledocs command line interface."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import __version__, engine, gitio, ledger, report
from . import mapping as mapping_mod
from .config import (
    CONFIG_NAME,
    DEFAULT_CONFIG_TEMPLATE,
    GATE_STRICT,
    GATE_WARN,
    LEDGER_DIR,
    Config,
    ConfigError,
    load,
)


def _repo_root() -> Path:
    try:
        return gitio.find_repo_root(Path.cwd())
    except gitio.GitError as exc:
        raise click.ClickException(str(exc)) from exc


def _load_config(repo_root: Path) -> Config:
    try:
        return load(repo_root)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc


def _resolve(repo_root: Path, cfg: Config) -> mapping_mod.MappingResult:
    return mapping_mod.resolve(cfg, gitio.ls_files(repo_root))


@click.group()
@click.version_option(version=__version__, prog_name="staledocs")
def main() -> None:
    """Deterministic drift detection between code and docs."""


@main.command()
@click.option(
    "--suggest",
    "with_suggest",
    is_flag=True,
    help="Propose pairs from each doc's own anchors (proposal only, never writes config).",
)
def init(with_suggest: bool) -> None:
    """Scaffold .staledocs.yaml and the ledger directory.

    With --suggest, anchors in every doc are resolved against the tree and
    a paste-ready pairs proposal is printed — on a fresh repo after the
    scaffold, or standalone when a config already exists.
    """
    repo_root = _repo_root()
    cfg_path = repo_root / CONFIG_NAME
    if cfg_path.exists():
        if with_suggest:
            _print_suggestions(repo_root)
            return
        raise click.ClickException(f"{CONFIG_NAME} already exists")

    tracked = gitio.ls_files(repo_root)
    top_dirs = sorted({f.split("/", 1)[0] for f in tracked if "/" in f})
    code_dirs = [d for d in top_dirs if d in ("src", "lib", "app", "scripts")] or (
        ["src"] if "src" in top_dirs else top_dirs[:1] or ["src"]
    )
    source_include = "\n".join(f'    - "{d}/**"' for d in code_dirs)
    docs_include = '    - "docs/**/*.md"\n    - "README.md"'

    cfg_path.write_text(
        DEFAULT_CONFIG_TEMPLATE.format(
            source_include=source_include, docs_include=docs_include
        ),
        encoding="utf-8",
    )
    (repo_root / LEDGER_DIR).mkdir(parents=True, exist_ok=True)
    (repo_root / LEDGER_DIR / ".gitkeep").write_text("", encoding="utf-8")
    # a config the tool just wrote is trivially acceptable as the baseline —
    # recording it here means the weakening gate only ever fires on a real
    # diff against something, never on "there was nothing before" (an
    # initialization is not a weakening, and agents refusing to self-approve
    # weakenings must not deadlock on it)
    ledger.write_config_ack(
        repo_root,
        ledger.config_snapshot(_load_config(repo_root)),
        note="initial baseline recorded by init (scaffold config, nothing weakened)",
    )
    click.echo(
        f"wrote {CONFIG_NAME} and {LEDGER_DIR}/ — edit the pairing, then run `staledocs check`"
    )
    click.echo(
        "config baseline recorded (edits from here on are diffed against the scaffold)"
    )
    if with_suggest:
        click.echo()
        _print_suggestions(repo_root)


def _print_suggestions(repo_root: Path) -> None:
    from . import suggest as suggest_mod

    cfg = _load_config(repo_root)
    suggestions = suggest_mod.build(repo_root, cfg, gitio.ls_files(repo_root))
    if not suggestions:
        click.echo("no docs found to suggest pairs for")
        return
    click.echo(suggest_mod.render(suggestions))


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output (the agent API).")
@click.option("--all", "show_green", is_flag=True, help="Show green pairs too.")
@click.option(
    "--gate",
    type=click.Choice([GATE_WARN, GATE_STRICT]),
    default=None,
    help="Override the configured gate for this run.",
)
def check(as_json: bool, show_green: bool, gate: str | None) -> None:
    """Run all deterministic checks (pair freshness, anchors, coverage)."""
    repo_root = _repo_root()
    cfg = _load_config(repo_root)
    effective_gate = gate or cfg.gate
    resolved = _resolve(repo_root, cfg)
    result = engine.run_check(repo_root, cfg, resolved)

    if as_json:
        click.echo(report.render_json(result, resolved, effective_gate), nl=False)
    else:
        click.echo(report.render_human(result, show_green=show_green))

    if effective_gate == GATE_STRICT and result.red_count() > 0:
        sys.exit(1)


def _refresh_config_baseline(repo_root: Path, cfg: Config) -> None:
    """Advance the config baseline at a natural write point — but only when
    the current config weakens nothing against it. A pending weakening must
    go through `ack --config` explicitly."""
    snapshot = ledger.config_snapshot(cfg)
    baseline = ledger.read_config_ack(repo_root)
    if baseline is not None and not ledger.config_weakenings(baseline, snapshot):
        ledger.write_config_ack(repo_root, snapshot, note="advanced by pair ack (no weakening)")


@main.command()
@click.argument("docs", nargs=-1)
@click.option("--all", "ack_all", is_flag=True, help="Ack every mapped pair.")
@click.option("--broken", "ack_broken", is_flag=True, help="Ack every non-green pair.")
@click.option("--prune", is_flag=True, help="Drop ledger entries whose doc is no longer mapped.")
@click.option(
    "--config",
    "ack_config",
    is_flag=True,
    help="Accept the current .staledocs.yaml as the checked baseline.",
)
@click.option(
    "--confirm",
    default=None,
    metavar="TOKEN",
    help="Evidence token echoed from the pending step.",
)
@click.option("-m", "--note", default="", help="Note recorded with the ack.")
def ack(
    docs: tuple[str, ...],
    ack_all: bool,
    ack_broken: bool,
    prune: bool,
    ack_config: bool,
    confirm: str | None,
    note: str,
) -> None:
    """Record 'this pair is coherent as of now' (the hanko).

    A broken pair acks in two steps: the first run prints the evidence (what
    the doc says next to what changed) plus a token; the second run passes
    --confirm TOKEN with a note that names something from that evidence.
    Green pairs re-ack directly. `Staledocs-Ack:` commit trailers are
    unaffected — that path is the human shortcut.
    """
    repo_root = _repo_root()
    cfg = _load_config(repo_root)

    if ack_config:
        if not note.strip():
            raise click.UsageError("--config requires a non-empty --note")
        snapshot = ledger.config_snapshot(cfg)
        baseline = ledger.read_config_ack(repo_root)
        weakenings = (
            ledger.config_weakenings(baseline, snapshot) if baseline is not None else []
        )
        ledger.write_config_ack(repo_root, snapshot, note=note)
        if weakenings:
            for w in weakenings:
                click.echo(f"accepted weakening: {w}")
        if baseline is None:
            # first record: there was no prior baseline, so nothing was
            # weakened — this is initialization, not a weakening approval
            click.echo(
                "initial config baseline recorded (no prior baseline — "
                "nothing weakened, this is not a weakening approval)"
            )
        else:
            click.echo("config baseline recorded")
        if not (docs or ack_all or ack_broken or prune):
            return

    resolved = _resolve(repo_root, cfg)
    by_doc = {p.doc: p for p in resolved.pairs}

    if prune:
        mapped = set(by_doc)
        pruned = 0
        for doc in ledger.known_docs(repo_root):
            if doc not in mapped and ledger.remove_entry(repo_root, doc):
                click.echo(f"pruned ledger entry: {doc}")
                pruned += 1
        if pruned == 0:
            click.echo("nothing to prune")
        if not (docs or ack_all or ack_broken):
            return

    mention_ctx = engine.make_mention_ctx(repo_root, cfg)
    reports: dict[str, engine.PairReport] = {}

    def _report(doc: str) -> engine.PairReport:
        if doc not in reports:
            reports[doc] = engine.check_pair(repo_root, by_doc[doc], mention_ctx)
        return reports[doc]

    targets: list[str]
    if ack_all:
        targets = sorted(by_doc)
    elif ack_broken:
        targets = sorted(d for d in by_doc if _report(d).state != engine.GREEN)
        if not targets:
            click.echo("no broken pairs — nothing to ack")
            return
    elif docs:
        targets = [d.strip().lstrip("./") for d in docs]
        for doc in targets:
            if doc not in by_doc:
                raise click.ClickException(
                    f"not a mapped pair doc: {doc} (see `staledocs pairs`)"
                )
    else:
        raise click.UsageError("name docs to ack, or pass --all / --broken")

    green = [d for d in targets if _report(d).state == engine.GREEN]
    pending = [d for d in targets if d not in green]

    # step 2: confirm against the token computed when the evidence was shown.
    # One token confirms exactly one pending pair — a single token that
    # unlocks N pairs would let an unread doc ride through on a note written
    # about a different one, which is the exact hole the two-step ack exists
    # to close. Bulk flags only batch step 1 (all evidence + all tokens in
    # one run); every confirm names its own doc.
    if pending and confirm is not None:
        if len(pending) > 1:
            raise click.UsageError(
                "one --confirm token acks one pair — run the per-doc commands "
                "printed by the evidence step (bulk flags batch the evidence, "
                "not the confirmation)"
            )
        token = engine.aggregate_token(
            [engine.pair_fingerprint(repo_root, by_doc[pending[0]])]
        )
        if confirm != token:
            raise click.ClickException(
                "evidence token mismatch — the pair moved since the evidence was shown; "
                "rerun `staledocs ack` and read the fresh evidence"
            )
        if not note.strip():
            raise click.UsageError("confirming an ack requires a non-empty --note")
        if not engine.note_references_evidence(note, _report(pending[0])):
            rep = _report(pending[0])
            if rep.state == engine.UNACKED and rep.claims:
                raise click.ClickException(
                    "note must name one of the doc's own claims shown in the "
                    "evidence (a quoted path or identifier) — the doc or file "
                    "name alone is the vacuous stamp the first ack refuses"
                )
            raise click.ClickException(
                "note must name something from the evidence "
                "(a changed file, a quoted anchor, or the doc)"
            )
    elif pending:
        # step 1: show the evidence and hand out one token per pair
        if len(pending) > 1:
            click.echo(f"{len(pending)} pending pairs — each needs its own confirm:")
            click.echo()
        for doc in pending:
            click.echo(report.render_evidence(engine.build_evidence(repo_root, _report(doc))))
            token = engine.aggregate_token(
                [engine.pair_fingerprint(repo_root, by_doc[doc])]
            )
            click.echo(
                f"pending: read the evidence above, then\n"
                f"  staledocs ack {doc} --confirm {token} -m '<what you verified>'"
            )
            click.echo()
        for doc in green:
            engine.ack_pair(repo_root, by_doc[doc], note=note)
            click.echo(f"acked {doc} (green refresh)")
        sys.exit(3)  # 3 = pending confirmation (2 is click's usage-error code)

    for doc in targets:
        engine.ack_pair(repo_root, by_doc[doc], note=note)
        click.echo(f"acked {doc} ({len(by_doc[doc].code_files)} code files)")
    _refresh_config_baseline(repo_root, cfg)


@main.command()
@click.argument("docs", nargs=-1)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def explain(docs: tuple[str, ...], as_json: bool) -> None:
    """Show the evidence for broken pairs: the doc's words next to the change.

    Read-only and never gates — this is the compare-these-two view for a
    human review or an agent repair loop (L3 input). Name docs to narrow it.
    """
    repo_root = _repo_root()
    cfg = _load_config(repo_root)
    resolved = _resolve(repo_root, cfg)
    mention_ctx = engine.make_mention_ctx(repo_root, cfg)
    wanted = {d.strip().lstrip("./") for d in docs} if docs else None

    blocks: list[dict] = []
    for pair in resolved.pairs:
        if wanted is not None and pair.doc not in wanted:
            continue
        rep = engine.check_pair(repo_root, pair, mention_ctx)
        if rep.state == engine.GREEN:
            continue
        evidence = engine.build_evidence(repo_root, rep)
        evidence["token"] = engine.pair_fingerprint(repo_root, pair)
        blocks.append(evidence)

    if as_json:
        import json as _json

        click.echo(_json.dumps({"schema": 1, "pairs": blocks}, indent=2))
        return
    if not blocks:
        click.echo("nothing to explain — all pairs green")
        return
    for evidence in blocks:
        click.echo(report.render_evidence(evidence))
        click.echo()


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.option(
    "--health",
    is_flag=True,
    help="Diagnostic view: anchor density and ack age per pair (never gates).",
)
def pairs(as_json: bool, health: bool) -> None:
    """Show how every doc and source file is classified."""
    repo_root = _repo_root()
    cfg = _load_config(repo_root)
    resolved = _resolve(repo_root, cfg)

    if health:
        _pairs_health(repo_root, cfg, resolved, as_json)
        return

    if as_json:
        import json as _json

        payload = {
            "pairs": [
                {
                    "doc": p.doc,
                    "origin": p.origin,
                    "code_patterns": p.code_patterns,
                    "code_files": p.code_files,
                }
                for p in resolved.pairs
            ],
            "standalone": resolved.standalone_docs,
            "global": resolved.global_docs,
            "unclassified_docs": resolved.unclassified_docs,
            "uncovered_source": resolved.uncovered_source,
        }
        click.echo(_json.dumps(payload, indent=2))
        return

    for p in resolved.pairs:
        click.echo(f"pair ({p.origin}): {p.doc}")
        for f in p.code_files:
            click.echo(f"    {f}")
    for d in resolved.standalone_docs:
        click.echo(f"standalone: {d}")
    for d in resolved.global_docs:
        click.echo(f"global: {d}")
    for d in resolved.unclassified_docs:
        click.echo(f"UNCLASSIFIED doc: {d}")
    for f in resolved.uncovered_source:
        click.echo(f"UNCOVERED source: {f}")


def _pairs_health(
    repo_root: Path, cfg: Config, resolved: mapping_mod.MappingResult, as_json: bool
) -> None:
    """Anchor density + ack age per pair. Diagnosis only, exit 0 always."""
    from . import anchors as anchors_mod

    ctx = engine.make_mention_ctx(repo_root, cfg)
    example_counts: dict[str, int] = {}
    if cfg.examples:
        from . import examples as examples_mod

        example_counts = examples_mod.build(
            repo_root, cfg.examples, list(resolved.doc_files)
        ).per_doc
    rows: list[dict] = []
    for pair in resolved.pairs:
        mentions = anchors_mod.doc_mention_index(
            repo_root, pair.doc, ctx.anchors_rule, ctx.all_files, ctx.all_dirs, ctx.path_roots
        )
        rep = engine.check_pair(repo_root, pair, ctx)
        commits_behind: int | None = None
        if rep.ack_commit and gitio.commit_exists(repo_root, rep.ack_commit):
            commits_behind = sum(
                1
                for c in gitio.commits_since(repo_root, rep.ack_commit)
                if c.sha != gitio.WORKTREE
            )
        rows.append(
            {
                "doc": pair.doc,
                "state": rep.state,
                "code_files": len(pair.code_files),
                "path_anchors": len(mentions.path_files),
                "ident_anchors": len(mentions.idents),
                "total_anchors": mentions.total_anchors,
                "always_red": mentions.total_anchors == 0,
                "commits_since_ack": commits_behind,
                "wired_examples": example_counts.get(pair.doc, 0),
            }
        )

    if as_json:
        import json as _json

        click.echo(_json.dumps({"schema": 1, "health": rows}, indent=2))
        return
    for r in rows:
        flags = []
        if r["always_red"]:
            flags.append("NO ANCHORS — every code move reds this doc; quote paths/identifiers")
        if r["code_files"] > 50 and r["path_anchors"] + r["ident_anchors"] < 3:
            flags.append("wide pair, few anchors — grading has little to work with")
        age = (
            "" if r["commits_since_ack"] is None
            else f", {r['commits_since_ack']} commits since ack"
        )
        click.echo(
            f"{r['doc']}: {r['state']}, {r['code_files']} code files, "
            f"anchors {r['path_anchors']} path + {r['ident_anchors']} ident{age}"
        )
        for f in flags:
            click.echo(f"    ! {f}")


if __name__ == "__main__":
    main()
