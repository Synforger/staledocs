"""Thin git plumbing layer.

Everything staledocs knows about change comes from git: blob hashes for
"did this file move since the ack", commit topology for "did the code and
the doc move together", and trailers for in-commit acks. No wall-clock, no
mtime — fingerprints only.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

ACK_TRAILER = "Staledocs-Ack"


class GitError(Exception):
    """Raised when a git invocation fails or the cwd is not a repository."""


def _run(repo_root: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def find_repo_root(start: Path) -> Path:
    out = _run(start, "rev-parse", "--show-toplevel", check=False).strip()
    if not out:
        raise GitError("not inside a git repository")
    return Path(out)


def head_commit(repo_root: Path) -> str | None:
    """Current HEAD sha, or None on a repo with no commits yet."""
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def ls_files(repo_root: Path) -> list[str]:
    """Tracked files plus untracked-but-not-ignored files (POSIX relative)."""
    out = _run(
        repo_root,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
    )
    return [line for line in out.splitlines() if line.strip()]


def hash_object(repo_root: Path, rel_path: str) -> str | None:
    """Blob sha of the working-tree content, or None when the file is gone."""
    abs_path = repo_root / rel_path
    if not abs_path.is_file():
        return None
    out = _run(repo_root, "hash-object", "--", rel_path)
    return out.strip()


def commit_exists(repo_root: Path, sha: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "-e", f"{sha}^{{commit}}"],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


@dataclass
class Commit:
    sha: str
    files: set[str]
    trailer_acks: set[str]


WORKTREE = "WORKTREE"


def commits_since(repo_root: Path, since_sha: str) -> list[Commit]:
    """Commits after `since_sha` up to HEAD (oldest first), with touched files
    and any `Staledocs-Ack:` trailer values.

    A pseudo-commit `WORKTREE` is appended last, carrying uncommitted changes
    (staged + unstaged + untracked) so the co-movement rule treats "edited
    both, not committed yet" the same as "committed both together".
    """
    commits: list[Commit] = []
    out = _run(
        repo_root,
        "log",
        "--reverse",
        "--name-only",
        f"--format=%x01%H%x02%(trailers:key={ACK_TRAILER},valueonly=true,separator=%x03)",
        f"{since_sha}..HEAD",
    )
    current: Commit | None = None
    for line in out.splitlines():
        if line.startswith("\x01"):
            body = line[1:]
            sha, _, trailers = body.partition("\x02")
            acks = {t.strip() for t in trailers.split("\x03") if t.strip()}
            current = Commit(sha=sha, files=set(), trailer_acks=acks)
            commits.append(current)
        elif line.strip() and current is not None:
            current.files.add(line.strip())

    dirty = worktree_dirty_files(repo_root)
    if dirty:
        commits.append(Commit(sha=WORKTREE, files=dirty, trailer_acks=set()))
    return commits


def worktree_dirty_files(repo_root: Path) -> set[str]:
    """Files that differ from HEAD (staged, unstaged, or untracked)."""
    out = _run(repo_root, "status", "--porcelain", "--untracked-files=all")
    files: set[str] = set()
    for line in out.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        # rename entries look like "old -> new"; both sides moved
        if " -> " in path:
            old, _, new = path.partition(" -> ")
            files.add(old.strip().strip('"'))
            files.add(new.strip().strip('"'))
        else:
            files.add(path.strip().strip('"'))
    return files


def blob_at_commit(repo_root: Path, sha: str, rel_path: str) -> str | None:
    """Blob sha of `rel_path` as of commit `sha`, or None if absent there."""
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", f"{sha}:{rel_path}"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def blob_text(repo_root: Path, blob_sha: str) -> str | None:
    """Content of a blob object, or None when git does not have it.

    An ack taken on a dirty worktree records a hash the object database may
    never have stored — callers must treat None as "old content unknown".
    """
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "blob", blob_sha],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def changed_lines(old_text: str | None, new_text: str | None) -> list[str]:
    """Added/removed line text between two file versions (pure difflib —
    no object-database dependency, deterministic).

    None on either side means the file is absent there: every line of the
    other side counts as changed.
    """
    import difflib

    old_lines = old_text.splitlines() if old_text is not None else []
    new_lines = new_text.splitlines() if new_text is not None else []
    if not old_lines:
        return list(new_lines)
    if not new_lines:
        return list(old_lines)
    out: list[str] = []
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        out.extend(old_lines[i1:i2])
        out.extend(new_lines[j1:j2])
    return out


def ignored_paths(repo_root: Path, candidates: list[str]) -> set[str]:
    """Subset of `candidates` that .gitignore rules would ignore.

    Deterministic from repo state (works identically on a fresh CI checkout
    where the runtime files themselves do not exist).
    """
    if not candidates:
        return set()
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "check-ignore", "--stdin"],
        input="\n".join(candidates) + "\n",
        capture_output=True,
        text=True,
    )
    # exit 0 = some ignored, 1 = none ignored, 128 = error
    if proc.returncode not in (0, 1):
        return set()
    return {line for line in proc.stdout.splitlines() if line}
