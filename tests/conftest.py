"""Shared fixtures: real throwaway git repos, no mocks in the core path."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


class Repo:
    def __init__(self, root: Path):
        self.root = root

    def git(self, *args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout

    def write(self, rel: str, content: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def commit(self, message: str, *paths: str) -> str:
        if paths:
            self.git("add", "--", *paths)
        else:
            self.git("add", "-A")
        self.git("commit", "-m", message, "--no-verify", "--quiet")
        return self.git("rev-parse", "HEAD").strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Repo:
    root = tmp_path / "repo"
    root.mkdir()
    r = Repo(root)
    r.git("init", "-b", "main", "--quiet")
    r.git("config", "user.name", "tester")
    r.git("config", "user.email", "tester@example.invalid")
    r.git("config", "core.hooksPath", "/dev/null")
    r.git("config", "commit.gpgsign", "false")
    return r


@pytest.fixture()
def paired_repo(repo: Repo) -> Repo:
    """A repo with one doc<->code pair, config, and an initial commit."""
    repo.write("src/auth/token.py", "def issue_token():\n    return 'tok'\n")
    repo.write("src/auth/session.py", "def open_session():\n    return 1\n")
    repo.write("docs/auth.md", "# Auth\n\nUses `issue_token` from `src/auth/token.py`.\n")
    repo.write(
        ".staledocs.yaml",
        """\
version: 1
gate: warn
source:
  include: ["src/**"]
docs:
  include: ["docs/**/*.md"]
pairs:
  - doc: docs/auth.md
    code: ["src/auth/**"]
""",
    )
    repo.commit("initial")
    return repo
