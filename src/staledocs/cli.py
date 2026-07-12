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
def init() -> None:
    """Scaffold .staledocs.yaml and the ledger directory."""
    repo_root = _repo_root()
    cfg_path = repo_root / CONFIG_NAME
    if cfg_path.exists():
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
    click.echo(
        f"wrote {CONFIG_NAME} and {LEDGER_DIR}/ — edit the pairing, then run `staledocs check`"
    )


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


@main.command()
@click.argument("docs", nargs=-1)
@click.option("--all", "ack_all", is_flag=True, help="Ack every mapped pair.")
@click.option("--broken", "ack_broken", is_flag=True, help="Ack every non-green pair.")
@click.option("--prune", is_flag=True, help="Drop ledger entries whose doc is no longer mapped.")
@click.option("-m", "--note", default="", help="Free-form note recorded with the ack.")
def ack(docs: tuple[str, ...], ack_all: bool, ack_broken: bool, prune: bool, note: str) -> None:
    """Record 'this pair is coherent as of now' (the hanko)."""
    repo_root = _repo_root()
    cfg = _load_config(repo_root)
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

    targets: list[str]
    if ack_all:
        targets = sorted(by_doc)
    elif ack_broken:
        targets = sorted(
            p.doc for p in resolved.pairs if engine.check_pair(repo_root, p).state != engine.GREEN
        )
        if not targets:
            click.echo("no broken pairs — nothing to ack")
            return
    elif docs:
        targets = [d.strip().lstrip("./") for d in docs]
    else:
        raise click.UsageError("name docs to ack, or pass --all / --broken")

    for doc in targets:
        pair = by_doc.get(doc)
        if pair is None:
            raise click.ClickException(f"not a mapped pair doc: {doc} (see `staledocs pairs`)")
        engine.ack_pair(repo_root, pair, note=note)
        click.echo(f"acked {doc} ({len(pair.code_files)} code files)")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def pairs(as_json: bool) -> None:
    """Show how every doc and source file is classified."""
    repo_root = _repo_root()
    cfg = _load_config(repo_root)
    resolved = _resolve(repo_root, cfg)

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


if __name__ == "__main__":
    main()
