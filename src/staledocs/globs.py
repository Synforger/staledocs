"""Glob matching with `**` support, shared by mapping and config filters.

Semantics (CODEOWNERS-flavoured):
  - patterns match repo-relative POSIX paths (no leading `./`)
  - `*`  matches within one path segment
  - `?`  matches a single character within a segment
  - `**` matches across segments; `a/**` matches everything under `a/`
    (but not `a` itself), `**/x.py` matches `x.py` at any depth
  - a pattern with no glob characters is an exact path match, except that a
    pattern naming a directory prefix (`src/auth`) matches everything under it
"""

from __future__ import annotations

import re
from functools import lru_cache

_GLOB_CHARS = ("*", "?", "[")


@lru_cache(maxsize=4096)
def _compile(pattern: str) -> re.Pattern[str]:
    out: list[str] = ["^"]
    i = 0
    n = len(pattern)
    while i < n:
        if pattern.startswith("**/", i):
            out.append(r"(?:[^/]+/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(r".*")
            i += 2
        elif pattern[i] == "*":
            out.append(r"[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append(r"[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def matches(pattern: str, path: str) -> bool:
    """Return True when `path` matches `pattern`.

    A literal pattern (no glob characters) also matches as a directory
    prefix: `src/auth` matches `src/auth/token.py`.
    """
    pattern = pattern.strip().lstrip("./")
    path = path.lstrip("./")
    if not pattern:
        return False
    if _compile(pattern).match(path):
        return True
    if not any(c in pattern for c in _GLOB_CHARS):
        return path.startswith(pattern.rstrip("/") + "/")
    return False


def match_any(patterns: list[str], path: str) -> bool:
    return any(matches(p, path) for p in patterns)


def filter_paths(paths: list[str], include: list[str], exclude: list[str]) -> list[str]:
    """Paths matching at least one include pattern and no exclude pattern."""
    return [
        p
        for p in paths
        if match_any(include, p) and not match_any(exclude, p)
    ]
