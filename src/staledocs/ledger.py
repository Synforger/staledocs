"""Per-pair ack ledger under `.staledocs/pairs/`.

One JSON file per pair keeps merge conflicts local to the pair that actually
double-acked, and the conflict resolution rule is fail-safe: a file that does
not parse (conflict markers included) is treated as *no ack at all*, so the
pair simply shows up broken again and gets re-checked. A merge can never
silently manufacture a green state.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import LEDGER_DIR

SCHEMA = 1


@dataclass
class Ack:
    commit: str | None  # None = acked before the first commit existed
    doc_blob: str
    code_blobs: dict[str, str]
    at: str
    note: str = ""


def pair_id(doc: str) -> str:
    """Stable filename-safe id for a doc path."""
    slug = re.sub(r"[^A-Za-z0-9._-]", "__", doc)
    digest = hashlib.sha1(doc.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def _path(repo_root: Path, doc: str) -> Path:
    return repo_root / LEDGER_DIR / f"{pair_id(doc)}.json"


def read_ack(repo_root: Path, doc: str) -> Ack | None:
    """The recorded ack, or None when absent or unreadable (fail-safe)."""
    path = _path(repo_root, doc)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return None
    ack = raw.get("ack")
    if not isinstance(ack, dict):
        return None
    doc_blob = ack.get("doc_blob")
    code_blobs = ack.get("code_blobs")
    if not isinstance(doc_blob, str) or not isinstance(code_blobs, dict):
        return None
    return Ack(
        commit=ack.get("commit"),
        doc_blob=doc_blob,
        code_blobs={str(k): str(v) for k, v in code_blobs.items()},
        at=str(ack.get("at", "")),
        note=str(ack.get("note", "")),
    )


def write_ack(
    repo_root: Path,
    doc: str,
    commit: str | None,
    doc_blob: str,
    code_blobs: dict[str, str],
    note: str = "",
) -> Path:
    path = _path(repo_root, doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "doc": doc,
        "ack": {
            "commit": commit,
            "doc_blob": doc_blob,
            "code_blobs": dict(sorted(code_blobs.items())),
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "note": note,
        },
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def known_docs(repo_root: Path) -> list[str]:
    """Doc paths that currently hold a readable ledger entry."""
    ledger = repo_root / LEDGER_DIR
    if not ledger.is_dir():
        return []
    docs: list[str] = []
    for path in sorted(ledger.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        doc = raw.get("doc") if isinstance(raw, dict) else None
        if isinstance(doc, str):
            docs.append(doc)
    return docs


def remove_entry(repo_root: Path, doc: str) -> bool:
    path = _path(repo_root, doc)
    if path.is_file():
        path.unlink()
        return True
    return False


# --- config baseline (the anti-backdoor ledger) -----------------------------
#
# Weakening the checks (dropping a pair, downgrading the gate, widening the
# ignore list) must itself be a checked event. The accepted config lives as a
# structural snapshot next to the pair ledger; `check` compares the current
# config against it and reds any weakening until `ack --config` records the
# acceptance with a note.

CONFIG_ACK_FILE = ".staledocs/config-ack.json"


def config_snapshot(cfg: object) -> dict:
    """The weakening-relevant surface of a Config, as plain data."""
    return {
        "gate": cfg.gate,
        "pair_docs": sorted(p.doc for p in cfg.pairs),
        "source_include": sorted(cfg.source_include),
        "source_exclude": sorted(cfg.source_exclude),
        "docs_include": sorted(cfg.docs_include),
        "docs_exclude": sorted(cfg.docs_exclude),
        "anchors": {
            "min_length": cfg.anchors.min_length,
            "ignore": sorted(cfg.anchors.ignore),
            "include_fenced": cfg.anchors.include_fenced,
        },
        "examples_wired": sorted(
            tag for tag, runner in getattr(cfg, "examples", {}).items() if runner
        ),
    }


def read_config_ack(repo_root: Path) -> dict | None:
    path = repo_root / CONFIG_ACK_FILE
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return None
    accepted = raw.get("accepted")
    return accepted if isinstance(accepted, dict) else None


def write_config_ack(repo_root: Path, snapshot: dict, note: str = "") -> Path:
    path = repo_root / CONFIG_ACK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "accepted": snapshot,
        "note": note,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def config_weakenings(old: dict, new: dict) -> list[str]:
    """Human-readable list of ways `new` checks less than `old`.

    Only weakening directions fire — strengthening (gate up, pair added,
    ignore removed) never does, so routine config growth stays silent.
    """
    out: list[str] = []
    if old.get("gate") == "strict" and new.get("gate") == "warn":
        out.append("gate downgraded: strict -> warn")
    for doc in old.get("pair_docs", []):
        if doc not in new.get("pair_docs", []):
            out.append(f"pair removed: {doc}")
    for pat in old.get("source_include", []):
        if pat not in new.get("source_include", []):
            out.append(f"source scope narrowed: include dropped {pat!r}")
    for pat in new.get("source_exclude", []):
        if pat not in old.get("source_exclude", []):
            out.append(f"source scope narrowed: exclude added {pat!r}")
    for pat in old.get("docs_include", []):
        if pat not in new.get("docs_include", []):
            out.append(f"docs scope narrowed: include dropped {pat!r}")
    for pat in new.get("docs_exclude", []):
        if pat not in old.get("docs_exclude", []):
            out.append(f"docs scope narrowed: exclude added {pat!r}")
    old_a = old.get("anchors", {})
    new_a = new.get("anchors", {})
    if new_a.get("min_length", 0) > old_a.get("min_length", 0):
        out.append(
            f"anchor min_length raised: {old_a.get('min_length')} -> {new_a.get('min_length')}"
        )
    for tok in new_a.get("ignore", []):
        if tok not in old_a.get("ignore", []):
            out.append(f"anchor ignore added: {tok!r}")
    if old_a.get("include_fenced") and not new_a.get("include_fenced"):
        out.append("fenced-block anchors disabled: include_fenced true -> false")
    for tag in old.get("examples_wired", []):
        if tag not in new.get("examples_wired", []):
            out.append(f"example runner unwired: {tag!r}")
    return out
