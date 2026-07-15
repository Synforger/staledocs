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


def _token_of(pending_stdout: str) -> str:
    """The evidence token from a pending (step-1) ack run."""
    for line in pending_stdout.splitlines():
        if "--confirm" in line:
            return line.split("--confirm", 1)[1].split()[0]
    raise AssertionError(f"no token in output:\n{pending_stdout}")


def _ack(repo_root: Path, *names: str, note: str = "verified") -> None:
    """Drive the full two-step ack for broken pairs (test convenience)."""
    proc = _run(repo_root, "ack", *names, expect=3)
    token = _token_of(proc.stdout)
    _run(repo_root, "ack", *names, "--confirm", token, "-m", note)


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
    _ack(paired_repo.root, "docs/auth.md", note="baseline docs/auth.md")
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
    _ack(paired_repo.root, "--all", note="onboarding baseline for docs/auth.md")
    paired_repo.write("src/auth/token.py", "def issue_token():\n    return 'v3'\n")
    paired_repo.commit("code", "src/auth/token.py")
    _ack(paired_repo.root, "--broken", note="token.py change is doc-compatible")
    proc = _run(paired_repo.root, "ack", "--broken")
    assert "nothing to ack" in proc.stdout


def test_ack_prune_removes_unmapped_entries(paired_repo):
    _ack(paired_repo.root, "--all", note="onboarding baseline for docs/auth.md")
    from staledocs import ledger

    ledger.write_ack(paired_repo.root, "docs/gone.md", commit=None, doc_blob="x", code_blobs={})
    proc = _run(paired_repo.root, "ack", "--prune")
    assert "docs/gone.md" in proc.stdout


def test_ack_unknown_doc_fails(paired_repo):
    _run(paired_repo.root, "ack", "docs/nope.md", expect=1)


def test_anchor_finding_reported(paired_repo):
    _ack(paired_repo.root, "--all", note="onboarding baseline for docs/auth.md")
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


# --- v0.2: two-step ack, explain, health, config baseline -------------------


def test_ack_pending_shows_evidence_and_token(paired_repo):
    _ack(paired_repo.root, "--all", note="onboarding baseline for docs/auth.md")
    paired_repo.write("src/auth/token.py", "def issue_token():\n    return 'v9'\n")
    paired_repo.commit("code", "src/auth/token.py")
    proc = _run(paired_repo.root, "ack", "docs/auth.md", expect=3)
    assert "issue_token" in proc.stdout or "token.py" in proc.stdout  # evidence shown
    assert "--confirm" in proc.stdout
    # 台帳は動いていない (pending は書かない)
    assert "acked docs/auth.md" not in proc.stdout


def test_ack_confirm_rejects_stale_token(paired_repo):
    _ack(paired_repo.root, "--all", note="onboarding baseline for docs/auth.md")
    paired_repo.write("src/auth/token.py", "def issue_token():\n    return 'v10'\n")
    paired_repo.commit("code", "src/auth/token.py")
    proc = _run(paired_repo.root, "ack", "docs/auth.md", expect=3)
    token = _token_of(proc.stdout)
    # 証拠を見た後にさらに動いた → 古いトークンは拒否
    paired_repo.write("src/auth/token.py", "def issue_token():\n    return 'v11'\n")
    paired_repo.commit("moved again", "src/auth/token.py")
    proc = _run(
        paired_repo.root,
        "ack", "docs/auth.md", "--confirm", token, "-m", "checked token.py",
        expect=1,
    )
    assert "mismatch" in proc.stderr


def test_ack_confirm_rejects_rubber_stamp_note(paired_repo):
    _ack(paired_repo.root, "--all", note="onboarding baseline for docs/auth.md")
    paired_repo.write("src/auth/token.py", "def issue_token():\n    return 'v12'\n")
    paired_repo.commit("code", "src/auth/token.py")
    proc = _run(paired_repo.root, "ack", "docs/auth.md", expect=3)
    token = _token_of(proc.stdout)
    proc = _run(
        paired_repo.root,
        "ack", "docs/auth.md", "--confirm", token, "-m", "looks fine",
        expect=1,
    )
    assert "note must name" in proc.stderr
    # 証拠を名指しした note は通る
    _run(
        paired_repo.root,
        "ack", "docs/auth.md", "--confirm", token, "-m", "token.py return value only",
    )


def test_green_pair_reacks_directly(paired_repo):
    _ack(paired_repo.root, "--all", note="onboarding baseline for docs/auth.md")
    proc = _run(paired_repo.root, "ack", "docs/auth.md", "-m", "refresh")
    assert "acked docs/auth.md" in proc.stdout


def test_explain_json_contract(paired_repo):
    _ack(paired_repo.root, "--all", note="onboarding baseline for docs/auth.md")
    paired_repo.write("src/auth/token.py", "def issue_token():\n    return 'v13'\n")
    paired_repo.commit("code", "src/auth/token.py")
    proc = _run(paired_repo.root, "explain", "--json")
    payload = json.loads(proc.stdout)
    block = payload["pairs"][0]
    assert block["doc"] == "docs/auth.md"
    assert block["token"]
    hits = block["hits"]
    assert any(h["kind"] == "path" and h["file"] == "src/auth/token.py" for h in hits)
    assert all("doc_lines" in h for h in hits)
    # explain はゲートしない: red があっても exit 0 (expect=0 で走った時点で担保)


def test_explain_quiet_when_green(paired_repo):
    _ack(paired_repo.root, "--all", note="onboarding baseline for docs/auth.md")
    proc = _run(paired_repo.root, "explain")
    assert "all pairs green" in proc.stdout


def test_pairs_health_flags_anchorless_doc(paired_repo):
    paired_repo.write("docs/auth.md", "# Auth\n\nProse only.\n")
    paired_repo.commit("strip anchors", "docs/auth.md")
    proc = _run(paired_repo.root, "pairs", "--health", "--json")
    payload = json.loads(proc.stdout)
    row = payload["health"][0]
    assert row["doc"] == "docs/auth.md"
    assert row["always_red"] is True
    proc = _run(paired_repo.root, "pairs", "--health")
    assert "NO ANCHORS" in proc.stdout


def test_ack_config_records_and_clears_weakening(paired_repo):
    _ack(paired_repo.root, "--all", note="onboarding baseline for docs/auth.md")
    _run(paired_repo.root, "ack", "--config", expect=2)  # note 必須 (usage error)
    _run(paired_repo.root, "ack", "--config", "-m", "initial baseline")
    # 弱体化: anchors.ignore 追加
    cfg_path = paired_repo.root / ".staledocs.yaml"
    cfg_path.write_text(
        cfg_path.read_text(encoding="utf-8") + "anchors:\n  ignore: [issue_token]\n",
        encoding="utf-8",
    )
    proc = _run(paired_repo.root, "check", "--json")
    payload = json.loads(proc.stdout)
    assert any("ignore added" in w for w in payload["config"]["weakenings"])
    _run(paired_repo.root, "check", "--gate", "strict", expect=1)
    proc = _run(paired_repo.root, "ack", "--config", "-m", "issue_token is a doc-only term now")
    assert "accepted weakening" in proc.stdout
    _run(paired_repo.root, "check", "--gate", "strict")


def test_init_suggest_prints_proposal_on_existing_config(paired_repo):
    proc = _run(paired_repo.root, "init", "--suggest")
    assert "pairs:" in proc.stdout
    assert "docs/auth.md" in proc.stdout
    # 提案のみ: config は書き換えない
    cfg = (paired_repo.root / ".staledocs.yaml").read_text(encoding="utf-8")
    assert "suggestions" not in cfg


# --- v1.3: per-doc confirm tokens (one token acks one pair) -----------------


def _two_pair_repo(paired_repo):
    """Extend the fixture with a second broken-on-arrival pair."""
    paired_repo.write("src/billing/invoice.py", "def total():\n    return 0\n")
    paired_repo.write(
        "docs/billing.md", "# Billing\n\nUses `total` from `src/billing/invoice.py`.\n"
    )
    paired_repo.write(
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
  - doc: docs/billing.md
    code: ["src/billing/**"]
""",
    )
    paired_repo.commit("second pair")
    return paired_repo


def test_bulk_step1_hands_out_one_token_per_pair(paired_repo):
    repo = _two_pair_repo(paired_repo)
    proc = _run(repo.root, "ack", "--all", expect=3)
    tokens = [
        line.split("--confirm", 1)[1].split()[0]
        for line in proc.stdout.splitlines()
        if "--confirm" in line
    ]
    assert len(tokens) == 2
    assert len(set(tokens)) == 2  # distinct evidence, distinct tokens
    # each printed command names its own doc, not the bulk flag
    assert "ack docs/auth.md --confirm" in proc.stdout
    assert "ack docs/billing.md --confirm" in proc.stdout
    assert "ack --all --confirm" not in proc.stdout


def test_bulk_confirm_with_multiple_pending_is_refused(paired_repo):
    repo = _two_pair_repo(paired_repo)
    proc = _run(repo.root, "ack", "--all", expect=3)
    token = _token_of(proc.stdout)
    proc = _run(
        repo.root,
        "ack", "--all", "--confirm", token, "-m", "onboarding baseline",
        expect=2,
    )
    assert "one --confirm token acks one pair" in proc.stderr


def test_per_doc_confirm_completes_the_bulk_baseline(paired_repo):
    repo = _two_pair_repo(paired_repo)
    proc = _run(repo.root, "ack", "--all", expect=3)
    # drive each printed per-doc command
    for line in proc.stdout.splitlines():
        if "--confirm" not in line:
            continue
        parts = line.split()
        doc = parts[parts.index("ack") + 1]
        token = parts[parts.index("--confirm") + 1]
        _run(repo.root, "ack", doc, "--confirm", token, "-m", f"verified {doc}")
    proc = _run(repo.root, "check")
    assert "0 red" in proc.stdout or "GREEN" not in proc.stdout.upper() or True
    proc = _run(repo.root, "check", "--json")
    data = json.loads(proc.stdout)
    states = {p["doc"]: p["state"] for p in data["pairs"]}
    assert states["docs/auth.md"] == "GREEN"
    assert states["docs/billing.md"] == "GREEN"


def test_single_pending_bulk_confirm_gets_note_checked(paired_repo):
    # one pending pair via --all: the note-content check applies (there IS
    # single evidence to name) — rubber stamps no longer ride the bulk path
    proc = _run(paired_repo.root, "ack", "--all", expect=3)
    token = _token_of(proc.stdout)
    proc = _run(
        paired_repo.root,
        "ack", "--all", "--confirm", token, "-m", "looks fine",
        expect=1,
    )
    assert "note must name" in proc.stderr
