"""L1 state machine on real git repos: green, stale, lag, amber, broken,
trailer acks, rename hints, fail-safe on corrupt ledger entries."""

from staledocs import engine, gitio, ledger
from staledocs.config import load
from staledocs.mapping import resolve


def _check(repo):
    cfg = load(repo.root)
    mapping = resolve(cfg, gitio.ls_files(repo.root))
    return engine.run_check(repo.root, cfg, mapping)


def _pair_state(repo, doc="docs/auth.md"):
    result = _check(repo)
    return next(p for p in result.pairs if p.doc == doc)


def _ack_all(repo):
    cfg = load(repo.root)
    mapping = resolve(cfg, gitio.ls_files(repo.root))
    for pair in mapping.pairs:
        engine.ack_pair(repo.root, pair)


def test_unacked_before_first_ack(paired_repo):
    assert _pair_state(paired_repo).state == engine.UNACKED


def test_green_after_ack(paired_repo):
    _ack_all(paired_repo)
    assert _pair_state(paired_repo).state == engine.GREEN


def test_doc_stale_when_code_moves_alone(paired_repo):
    _ack_all(paired_repo)
    paired_repo.write("src/auth/token.py", "def issue_token():\n    return 'tok2'\n")
    paired_repo.commit("code only", "src/auth/token.py")
    report = _pair_state(paired_repo)
    assert report.state == engine.DOC_STALE
    assert report.changed_code == ["src/auth/token.py"]


def test_code_lag_when_doc_moves_alone(paired_repo):
    _ack_all(paired_repo)
    paired_repo.write("docs/auth.md", "# Auth\n\nNew spec: `issue_token` gets a TTL.\n")
    paired_repo.commit("doc only", "docs/auth.md")
    assert _pair_state(paired_repo).state == engine.CODE_LAG


def test_amber_when_both_move_in_same_commit(paired_repo):
    _ack_all(paired_repo)
    paired_repo.write("src/auth/token.py", "def issue_token(ttl=60):\n    return 'tok'\n")
    paired_repo.write("docs/auth.md", "# Auth\n\n`issue_token` takes a TTL now.\n")
    paired_repo.commit("both together", "src/auth/token.py", "docs/auth.md")
    assert _pair_state(paired_repo).state == engine.AMBER


def test_broken_when_both_move_in_separate_commits(paired_repo):
    _ack_all(paired_repo)
    paired_repo.write("src/auth/token.py", "def issue_token(ttl=60):\n    return 'tok'\n")
    paired_repo.commit("code first", "src/auth/token.py")
    paired_repo.write("docs/auth.md", "# Auth\n\nRewritten independently.\n")
    paired_repo.commit("doc later", "docs/auth.md")
    assert _pair_state(paired_repo).state == engine.BROKEN


def test_amber_when_both_dirty_in_worktree(paired_repo):
    _ack_all(paired_repo)
    paired_repo.write("src/auth/token.py", "def issue_token(ttl=1):\n    return 'tok'\n")
    paired_repo.write("docs/auth.md", "# Auth\n\nEdited together, not committed.\n")
    assert _pair_state(paired_repo).state == engine.AMBER


def test_trailer_ack_advances_baseline(paired_repo):
    _ack_all(paired_repo)
    paired_repo.write("src/auth/token.py", "def issue_token(ttl=60):\n    return 'tok'\n")
    paired_repo.write("docs/auth.md", "# Auth\n\nTTL documented.\n")
    paired_repo.root.joinpath("msg").write_text(
        "sync auth\n\nStaledocs-Ack: docs/auth.md\n", encoding="utf-8"
    )
    paired_repo.git("add", "-A")
    paired_repo.git("commit", "-F", "msg", "--no-verify", "--quiet")
    (paired_repo.root / "msg").unlink()
    report = _pair_state(paired_repo)
    assert report.state == engine.GREEN
    assert "trailer" in report.detail


def test_trailer_ack_all_covers_every_pair(paired_repo):
    _ack_all(paired_repo)
    paired_repo.write("src/auth/token.py", "def issue_token(ttl=9):\n    return 'x'\n")
    paired_repo.root.joinpath("msg").write_text(
        "big sync\n\nStaledocs-Ack: all\n", encoding="utf-8"
    )
    paired_repo.git("add", "-A")
    paired_repo.git("commit", "-F", "msg", "--no-verify", "--quiet")
    (paired_repo.root / "msg").unlink()
    assert _pair_state(paired_repo).state == engine.GREEN


def test_rename_hint_on_identical_blob(paired_repo):
    _ack_all(paired_repo)
    content = (paired_repo.root / "src/auth/token.py").read_text(encoding="utf-8")
    (paired_repo.root / "src/auth/token.py").unlink()
    paired_repo.write("src/auth/token_v2.py", content)
    paired_repo.commit("rename")
    report = _pair_state(paired_repo)
    assert report.state == engine.DOC_STALE
    assert report.rename_hints == {"src/auth/token.py": "src/auth/token_v2.py"}


def test_corrupt_ledger_entry_is_failsafe_unacked(paired_repo):
    _ack_all(paired_repo)
    entry = (
        paired_repo.root / ".staledocs/pairs" / f"{ledger.pair_id('docs/auth.md')}.json"
    )
    entry.write_text(
        "<<<<<<< ours\n{}\n=======\n{}\n>>>>>>> theirs\n", encoding="utf-8"
    )
    assert _pair_state(paired_repo).state == engine.UNACKED


def test_stale_ledger_entry_reported(paired_repo):
    _ack_all(paired_repo)
    ledger.write_ack(
        paired_repo.root, "docs/deleted.md", commit=None, doc_blob="x", code_blobs={}
    )
    result = _check(paired_repo)
    assert result.stale_ledger_docs == ["docs/deleted.md"]
