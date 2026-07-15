"""Load and validate `.staledocs.yaml`.

The config is the single mapping truth: which files are source, which are
docs, and how they pair up. Everything here is declarative — the tool never
guesses beyond the explicit `mirror` convention the user opted into.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_NAME = ".staledocs.yaml"
LEDGER_DIR = ".staledocs/pairs"

GATE_WARN = "warn"
GATE_STRICT = "strict"


class ConfigError(Exception):
    """Raised for a missing, unparseable, or structurally invalid config."""


@dataclass
class PairRule:
    doc: str
    code: list[str]


@dataclass
class MirrorRule:
    enabled: bool = False
    docs_root: str = "docs"
    code_roots: list[str] = field(default_factory=lambda: ["src"])


# git branch names share slash syntax with paths (`feature/dark-mode`) but
# are never repo paths; docs quote them constantly. Tokens whose first
# segment is one of these prefixes skip path verification when no such
# tracked path exists. Empty list disables the skip.
DEFAULT_BRANCH_PREFIXES = ["feature", "fix", "hotfix", "release", "chore", "origin"]


@dataclass
class AnchorRule:
    min_length: int = 3
    ignore: list[str] = field(default_factory=list)
    include_fenced: bool = False
    path_roots: list[str] = field(default_factory=list)
    branch_prefixes: list[str] = field(default_factory=lambda: list(DEFAULT_BRANCH_PREFIXES))


@dataclass
class Config:
    gate: str = GATE_WARN
    source_include: list[str] = field(default_factory=list)
    source_exclude: list[str] = field(default_factory=list)
    docs_include: list[str] = field(default_factory=lambda: ["docs/**/*.md", "README.md"])
    docs_exclude: list[str] = field(default_factory=list)
    pairs: list[PairRule] = field(default_factory=list)
    mirror: MirrorRule = field(default_factory=MirrorRule)
    standalone: list[str] = field(default_factory=list)
    global_docs: list[str] = field(default_factory=list)
    anchors: AnchorRule = field(default_factory=AnchorRule)
    # executable-docs layer (opt-in): fence tag -> runner command string, or
    # None (declared display-only). Empty dict = layer off.
    examples: dict[str, str | None] = field(default_factory=dict)


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigError(msg)


def _str_list(raw: object, where: str) -> list[str]:
    if raw is None:
        return []
    _require(isinstance(raw, list), f"{where} must be a list of strings")
    for item in raw:  # type: ignore[union-attr]
        _require(
            isinstance(item, str) and item.strip() != "",
            f"{where} entries must be non-empty strings",
        )
    return [s.strip() for s in raw]  # type: ignore[union-attr]


def load(repo_root: Path) -> Config:
    path = repo_root / CONFIG_NAME
    _require(path.is_file(), f"{CONFIG_NAME} not found — run `staledocs init` first")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{CONFIG_NAME} is not valid YAML: {exc}") from exc
    _require(isinstance(raw, dict), f"{CONFIG_NAME} must be a YAML mapping")

    version = raw.get("version")
    _require(version == 1, f"unsupported config version {version!r} (expected 1)")

    cfg = Config()

    gate = raw.get("gate", GATE_WARN)
    _require(gate in (GATE_WARN, GATE_STRICT), "gate must be 'warn' or 'strict'")
    cfg.gate = gate

    source = raw.get("source") or {}
    _require(isinstance(source, dict), "source must be a mapping")
    cfg.source_include = _str_list(source.get("include"), "source.include")
    cfg.source_exclude = _str_list(source.get("exclude"), "source.exclude")
    _require(bool(cfg.source_include), "source.include must list at least one pattern")

    docs = raw.get("docs") or {}
    _require(isinstance(docs, dict), "docs must be a mapping")
    docs_include = _str_list(docs.get("include"), "docs.include")
    if docs_include:
        cfg.docs_include = docs_include
    cfg.docs_exclude = _str_list(docs.get("exclude"), "docs.exclude")

    pairs_raw = raw.get("pairs") or []
    _require(isinstance(pairs_raw, list), "pairs must be a list")
    seen_docs: set[str] = set()
    for i, entry in enumerate(pairs_raw):
        where = f"pairs[{i}]"
        _require(isinstance(entry, dict), f"{where} must be a mapping with 'doc' and 'code'")
        doc = entry.get("doc")
        _require(
            isinstance(doc, str) and doc.strip() != "",
            f"{where}.doc must be a non-empty string",
        )
        doc = doc.strip().lstrip("./")
        _require(doc not in seen_docs, f"{where}.doc duplicates an earlier pair for {doc!r}")
        seen_docs.add(doc)
        code = _str_list(entry.get("code"), f"{where}.code")
        _require(bool(code), f"{where}.code must list at least one pattern")
        cfg.pairs.append(PairRule(doc=doc, code=code))

    mirror_raw = raw.get("mirror") or {}
    _require(isinstance(mirror_raw, dict), "mirror must be a mapping")
    cfg.mirror = MirrorRule(
        enabled=bool(mirror_raw.get("enabled", False)),
        docs_root=str(mirror_raw.get("docs_root", "docs")).strip().rstrip("/"),
        code_roots=_str_list(mirror_raw.get("code_roots"), "mirror.code_roots") or ["src"],
    )

    cfg.standalone = _str_list(raw.get("standalone"), "standalone")
    cfg.global_docs = _str_list(raw.get("global"), "global")

    anchors_raw = raw.get("anchors") or {}
    _require(isinstance(anchors_raw, dict), "anchors must be a mapping")
    min_length = anchors_raw.get("min_length", 3)
    _require(
        isinstance(min_length, int) and min_length >= 1,
        "anchors.min_length must be a positive integer",
    )
    branch_prefixes = (
        _str_list(anchors_raw.get("branch_prefixes"), "anchors.branch_prefixes")
        if "branch_prefixes" in anchors_raw
        else list(DEFAULT_BRANCH_PREFIXES)
    )
    cfg.anchors = AnchorRule(
        min_length=min_length,
        branch_prefixes=branch_prefixes,
        ignore=_str_list(anchors_raw.get("ignore"), "anchors.ignore"),
        include_fenced=bool(anchors_raw.get("include_fenced", False)),
        path_roots=_str_list(anchors_raw.get("path_roots"), "anchors.path_roots"),
    )

    examples_raw = raw.get("examples") or {}
    _require(isinstance(examples_raw, dict), "examples must be a mapping of fence tag -> runner")
    for tag, runner in examples_raw.items():
        _require(
            isinstance(tag, str) and tag.strip() != "",
            "examples keys must be non-empty fence tags",
        )
        _require(
            runner is None
            or (isinstance(runner, str) and runner.strip() != "")
            or runner == "none",
            f"examples.{tag} must be a runner command string, or none (display-only)",
        )
        value = None if runner is None or runner == "none" else str(runner).strip()
        cfg.examples[tag.strip().lower()] = value

    return cfg


DEFAULT_CONFIG_TEMPLATE = """\
# staledocs — deterministic code<->docs drift detection.
# Docs: https://github.com/Synforger/staledocs
version: 1

# warn  = report only (onboarding mode)
# strict = non-zero exit on red findings (turn on once the pairing is complete)
gate: warn

source:
  include:
{source_include}
  exclude: []

docs:
  include:
{docs_include}
  exclude: []

# Explicit pairs (CODEOWNERS-style): a doc owns the code matched by its globs.
pairs: []
#  - doc: docs/auth.md
#    code: ["src/auth/**"]

# Convention pairing: docs/<name>.md <-> <code_root>/<name>/** or <code_root>/<name>.*
mirror:
  enabled: false
  docs_root: docs
  code_roots: [src]

# Docs that intentionally have no code counterpart (ops runbooks, philosophy).
standalone: []

# Whole-repo docs (README class): anchor verification only, no pair ledger.
global:
  - README.md

anchors:
  min_length: 3
  ignore: []       # tokens to skip (exact; entries with * ? [ also act as globs)
  include_fenced: false
  path_roots: []   # extra prefixes for resolving doc-quoted paths (e.g. [src])
  # quoted branch names (feature/dark-mode) are not paths; first segments
  # listed here skip path verification when no such tracked path exists.
  # branch_prefixes: [feature, fix, hotfix, release, chore, origin]

# Executable-docs layer (opt-in): map each fence tag to the runner that
# executes those blocks in your test suite, or to none (display-only).
# staledocs never runs anything — it inventories the blocks and flags
# unclassified tags so a forgotten wiring cannot stay silent.
# examples:
#   python: "pytest --doctest-glob='*.md'"
#   console: "byexample"
#   yaml: none
"""
