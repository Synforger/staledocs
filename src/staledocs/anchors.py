"""Anchor extraction and liveness verification (detection layer L2).

Docs naturally quote code: function names, CLI flags, config keys, paths.
Those quotes are the cheapest deterministic tripwire we have — extract every
code-looking inline span from the doc and verify it still exists on the code
side. No AST, no language awareness: the doc is parsed, the code is only
grepped, which is what keeps the tool language-agnostic and lets a finding
point at the exact doc line that rotted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import AnchorRule

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
# inline code spans; double-backtick spans are matched first
_SPAN_RE = re.compile(r"``([^`\n]+)``|`([^`\n]+)`")

_CAMEL_RE = re.compile(r"[a-z][A-Z]")
_UPPER_SNAKE_RE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$")
_NUMBERLIKE_RE = re.compile(r"^[\d\s.,:%+\-*/=<>()]+$")
_CODE_PUNCT = set("_./:-()[]<>=$@")


@dataclass
class Anchor:
    doc: str
    line: int
    token: str
    path_like: bool


@dataclass
class AnchorFinding:
    doc: str
    line: int
    token: str
    scope: str  # "pair" | "repo"


def _looks_like_code(token: str, min_length: int) -> bool:
    if len(token) < min_length:
        return False
    if any(ch.isspace() for ch in token):
        return False
    if _NUMBERLIKE_RE.match(token):
        return False
    # `<placeholder>` notation is documentation convention, not a greppable
    # anchor (`docs/<name>.md`, `--flag <value>`); skip rather than false-flag
    if "<" in token or ">" in token:
        return False
    if token.startswith("--") or token.startswith("-") and len(token) > 2:
        return True
    if any(ch in _CODE_PUNCT for ch in token):
        return True
    if _CAMEL_RE.search(token):
        return True
    return bool(_UPPER_SNAKE_RE.match(token))


def _is_path_like(token: str) -> bool:
    if "://" in token:  # URL, not a repo path
        return False
    return "/" in token.strip("/") or token.startswith("./")


def extract(doc: str, text: str, rule: AnchorRule) -> list[Anchor]:
    """Code-looking inline spans with their 1-indexed doc line numbers."""
    anchors: list[Anchor] = []
    in_fence = False
    fence_marker = ""
    ignore = set(rule.ignore)
    for lineno, line in enumerate(text.splitlines(), start=1):
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
            continue
        if in_fence and not rule.include_fenced:
            continue
        for m in _SPAN_RE.finditer(line):
            token = (m.group(1) or m.group(2) or "").strip()
            if not token or token in ignore:
                continue
            if not _looks_like_code(token, rule.min_length):
                continue
            anchors.append(
                Anchor(doc=doc, line=lineno, token=token, path_like=_is_path_like(token))
            )
    return anchors


def _normalize_path_token(token: str) -> str:
    token = token.strip()
    for prefix in ("./",):
        if token.startswith(prefix):
            token = token[len(prefix):]
    return token.strip("/")


def _path_exists(token: str, all_files: set[str], all_dirs: set[str]) -> bool:
    norm = _normalize_path_token(token)
    if not norm:
        return False
    if norm in all_files or norm in all_dirs:
        return True
    # tokens like "src/foo/*.py" or "docs/**" — satisfied if any file matches
    if any(ch in norm for ch in "*?["):
        from . import globs

        return any(globs.matches(norm, f) for f in all_files)
    return False


class CodeIndex:
    """Lazy substring index over a set of files (content loaded once)."""

    def __init__(self, repo_root: Path, files: list[str]):
        self._repo_root = repo_root
        self._files = files
        self._blob: str | None = None

    def _load(self) -> str:
        if self._blob is None:
            parts: list[str] = []
            for rel in self._files:
                try:
                    parts.append(
                        (self._repo_root / rel).read_text(encoding="utf-8", errors="ignore")
                    )
                except OSError:
                    continue
            self._blob = "\n".join(parts)
        return self._blob

    def contains(self, token: str) -> bool:
        return token in self._load()


def verify(
    repo_root: Path,
    doc: str,
    anchors: list[Anchor],
    pair_index: CodeIndex | None,
    repo_index: CodeIndex,
    all_files: set[str],
    all_dirs: set[str],
) -> list[AnchorFinding]:
    """Findings for anchors that no longer resolve.

    - path-like anchors verify against the repo file tree (repo-wide: a doc
      may legitimately reference paths outside its own pair)
    - identifier anchors first check the file tree (a bare filename like
      `README.ja.md` is a path reference without a slash), then the paired
      code only (searching the whole repo would let a same-named survivor
      elsewhere mask a rename); docs with no pair (global class) fall back
      to the repo-wide index
    - a dotted identifier (`anchors.include_fenced` config notation) passes
      when its final segment resolves, so doc-side key paths don't need to
      exist verbatim in code
    """
    findings: list[AnchorFinding] = []
    for anchor in anchors:
        if anchor.path_like:
            if not _path_exists(anchor.token, all_files, all_dirs):
                findings.append(
                    AnchorFinding(doc=doc, line=anchor.line, token=anchor.token, scope="repo")
                )
            continue
        if _path_exists(anchor.token, all_files, all_dirs):
            continue
        index = pair_index if pair_index is not None else repo_index
        scope = "pair" if pair_index is not None else "repo"
        if index.contains(anchor.token):
            continue
        if "." in anchor.token:
            tail = anchor.token.rsplit(".", 1)[-1]
            if len(tail) >= 2 and index.contains(tail):
                continue
        findings.append(
            AnchorFinding(doc=doc, line=anchor.line, token=anchor.token, scope=scope)
        )
    return findings


def dirs_of(files: set[str]) -> set[str]:
    dirs: set[str] = set()
    for f in files:
        parts = f.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    return dirs
