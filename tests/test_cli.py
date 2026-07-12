"""CLI integration: init/check/ack/pairs, JSON contract, gate exit codes."""

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(repo_root: Path, *args: str, expect: int = 0) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    proc = subprocess.run(
        [sys.executable, "-m", "staledocs.cli", *args],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )
    assert proc.returncode == expect, f"exit {proc.returncode}: {proc.stdout}\n{proc.stderr}"
    return proc


def test_init_scaffolds_config_and_ledger(repo):
    repo.write("src/x.py", "pass\n")
    repo.commit("seed")
    _run(repo.root, "init")
    assert (repo.root / ".staledocs.yaml").is_file()
    assert (repo.root / ".staledocs/pairs/.gitkeep").is_file()
    _run(repo.root, "init", expect=1)  # second init refuses


def test_check_json_contract(paired_repo):
    proc = _run(paired_repo.root, "check", "--json")
    payload = json.loads(proc.stdout)
    assert payload["schema"] == 1
    assert payload["summary"]["red"] >= 1  # unacked pair
    docs = [p["doc"] for p in payload["pairs"]]
    assert docs == ["docs/auth.md"]
    assert payload["pairs"][0]["state"] == "UNACKED"


def test_ack_then_green_and_strict_gate(paired_repo):
    _run(paired_repo.root, "ack", "docs/auth.md")
    proc = _run(paired_repo.root, "check", "--json", "--gate", "strict")
    payload = json.loads(proc.stdout)
    assert payload["pairs"][0]["state"] == "GREEN"
    assert payload["summary"]["red"] == 0

    # code moves alone -> strict gate exits non-zero
    paired_repo.write("src/auth/token.py", "def issue_token():\n    return 'v2'\n")
    paired_repo.commit("code only", "src/auth/token.py")
    _run(paired_repo.root, "check", "--gate", "strict", expect=1)
    # warn gate still exits zero
    _run(paired_repo.root, "check", "--gate", "warn")


def test_ack_all_and_broken(paired_repo):
    _run(paired_repo.root, "ack", "--all")
    paired_repo.write("src/auth/token.py", "def issue_token():\n    return 'v3'\n")
    paired_repo.commit("code", "src/auth/token.py")
    proc = _run(paired_repo.root, "ack", "--broken")
    assert "docs/auth.md" in proc.stdout
    proc = _run(paired_repo.root, "ack", "--broken")
    assert "nothing to ack" in proc.stdout


def test_ack_prune_removes_unmapped_entries(paired_repo):
    _run(paired_repo.root, "ack", "--all")
    from staledocs import ledger

    ledger.write_ack(paired_repo.root, "docs/gone.md", commit=None, doc_blob="x", code_blobs={})
    proc = _run(paired_repo.root, "ack", "--prune")
    assert "docs/gone.md" in proc.stdout


def test_ack_unknown_doc_fails(paired_repo):
    _run(paired_repo.root, "ack", "docs/nope.md", expect=1)


def test_anchor_finding_reported(paired_repo):
    _run(paired_repo.root, "ack", "--all")
    paired_repo.write(
        "docs/auth.md", "# Auth\n\nUses `vanished_function` from `src/auth/token.py`.\n"
    )
    paired_repo.write("src/auth/token.py", "def renamed():\n    return 1\n")
    paired_repo.commit("rename fn", "docs/auth.md", "src/auth/token.py")
    proc = _run(paired_repo.root, "check", "--json")
    payload = json.loads(proc.stdout)
    tokens = [a["token"] for a in payload["anchors"]]
    assert "vanished_function" in tokens


def test_coverage_findings_in_json(paired_repo):
    paired_repo.write("src/billing/new.py", "x = 1\n")
    paired_repo.write("docs/unowned.md", "# floats free\n")
    paired_repo.commit("add uncovered")
    proc = _run(paired_repo.root, "check", "--json")
    payload = json.loads(proc.stdout)
    assert "src/billing/new.py" in payload["coverage"]["uncovered_source"]
    assert "docs/unowned.md" in payload["coverage"]["unclassified_docs"]


def test_pairs_listing(paired_repo):
    proc = _run(paired_repo.root, "pairs")
    assert "pair (explicit): docs/auth.md" in proc.stdout
    assert "src/auth/token.py" in proc.stdout
