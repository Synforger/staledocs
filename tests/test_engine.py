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


def test_standalone_doc_gitignored_path_passes(paired_repo):
    _ack_all(paired_repo)
    paired_repo.write(".gitignore", "logs/\n")
    paired_repo.write("docs/runbook.md", "# Ops\n\nCheck `logs/app.log` when it breaks.\n")
    cfg_path = paired_repo.root / ".staledocs.yaml"
    cfg_path.write_text(
        cfg_path.read_text(encoding="utf-8") + "standalone: [docs/runbook.md]\n",
        encoding="utf-8",
    )
    paired_repo.commit("runbook")
    result = _check(paired_repo)
    tokens = [f.token for f in result.anchor_findings]
    assert "logs/app.log" not in tokens


def test_standalone_doc_dead_path_still_flags(paired_repo):
    _ack_all(paired_repo)
    paired_repo.write("docs/runbook.md", "# Ops\n\nSee `src/gone/thing.py` for details.\n")
    cfg_path = paired_repo.root / ".staledocs.yaml"
    cfg_path.write_text(
        cfg_path.read_text(encoding="utf-8") + "standalone: [docs/runbook.md]\n",
        encoding="utf-8",
    )
    paired_repo.commit("runbook")
    result = _check(paired_repo)
    assert "src/gone/thing.py" in [f.token for f in result.anchor_findings]


def test_unrelated_churn_downgrades_to_amber(paired_repo):
    # docs/auth.md は issue_token と token.py にしか言及していない。 session.py だけが
    # 動いた場合は「言及対象は無傷」 なので amber (= 反射 ack の燃料を断つ)。
    _ack_all(paired_repo)
    paired_repo.write("src/auth/session.py", "def open_session():\n    return 2\n")
    paired_repo.commit("unrelated churn", "src/auth/session.py")
    report = _pair_state(paired_repo)
    assert report.state == engine.AMBER
    assert "none referenced" in report.detail


def test_mentioned_path_change_stays_red(paired_repo):
    _ack_all(paired_repo)
    paired_repo.write("src/auth/token.py", "def issue_token():\n    return 'v2'\n")
    paired_repo.commit("mentioned file", "src/auth/token.py")
    report = _pair_state(paired_repo)
    assert report.state == engine.DOC_STALE
    assert report.mentioned_changed == ["src/auth/token.py"]


def test_quoted_identifier_in_changed_file_stays_red(paired_repo):
    # session.py 自体は docs に言及されないが、 docs が引用する識別子 issue_token を
    # 含む形に変わった → docs の語ってる対象が動いたとみなして red。
    _ack_all(paired_repo)
    paired_repo.write(
        "src/auth/session.py",
        "from .token import issue_token\n\ndef open_session():\n    return issue_token()\n",
    )
    paired_repo.commit("now touches issue_token", "src/auth/session.py")
    report = _pair_state(paired_repo)
    assert report.state == engine.DOC_STALE
    assert report.mentioned_changed == ["src/auth/session.py"]


# --- v0.2: line-granularity intersection, evidence, config ledger -----------


def test_ident_change_on_unrelated_lines_is_amber(paired_repo):
    # session.py が issue_token を含む状態で ack。その後 issue_token に触れない
    # 行だけ変更 → 変更行に引用識別子なし = amber。file 全体 grep (v0.1 加重 L1)
    # なら red になっていた境界ケース。
    paired_repo.write(
        "src/auth/session.py",
        "from .token import issue_token\n\ndef open_session():\n    return issue_token()\n",
    )
    paired_repo.commit("session uses issue_token", "src/auth/session.py")
    _ack_all(paired_repo)
    paired_repo.write(
        "src/auth/session.py",
        "from .token import issue_token\n\n"
        "def open_session():\n    log = True\n    return issue_token()\n",
    )
    paired_repo.commit("unrelated line added", "src/auth/session.py")
    report = _pair_state(paired_repo)
    assert report.state == engine.AMBER


def test_ident_change_on_quoted_line_is_red_with_evidence(paired_repo):
    _ack_all(paired_repo)
    paired_repo.write(
        "src/auth/session.py",
        "def open_session():\n    return issue_token(refresh=True)\n",
    )
    paired_repo.commit("touches issue_token line", "src/auth/session.py")
    report = _pair_state(paired_repo)
    assert report.state == engine.DOC_STALE
    hit = next(h for h in report.hit_anchors if h.kind == "ident")
    assert hit.token == "issue_token"
    assert hit.file == "src/auth/session.py"
    assert hit.doc_lines  # the doc line quoting it
    assert any("issue_token" in ln for ln in hit.changed_lines)


def test_anchorless_doc_stays_red(paired_repo):
    paired_repo.write("docs/auth.md", "# Auth\n\nProse only, no quotes at all.\n")
    paired_repo.commit("strip anchors", "docs/auth.md")
    _ack_all(paired_repo)
    paired_repo.write("src/auth/session.py", "def open_session():\n    return 3\n")
    paired_repo.commit("any code move", "src/auth/session.py")
    report = _pair_state(paired_repo)
    assert report.state == engine.DOC_STALE
    assert "no anchors" in report.detail


def test_note_references_evidence():
    report = engine.PairReport(
        doc="docs/auth.md",
        state=engine.DOC_STALE,
        origin="explicit",
        code_files=["src/auth/token.py"],
        changed_code=["src/auth/token.py"],
        hit_anchors=[engine.AnchorHit(file="src/auth/token.py", token="issue_token", kind="ident")],
    )
    assert engine.note_references_evidence("checked issue_token still per doc", report)
    assert engine.note_references_evidence("token.py refactor only", report)
    assert engine.note_references_evidence("auth.md wording still holds", report)
    assert not engine.note_references_evidence("looks fine", report)
    assert not engine.note_references_evidence("", report)


def test_pair_fingerprint_tracks_content(paired_repo):
    cfg = load(paired_repo.root)
    mapping = resolve(cfg, gitio.ls_files(paired_repo.root))
    pair = mapping.pairs[0]
    t1 = engine.pair_fingerprint(paired_repo.root, pair)
    assert t1 == engine.pair_fingerprint(paired_repo.root, pair)  # deterministic
    paired_repo.write("src/auth/token.py", "def issue_token():\n    return 'moved'\n")
    t2 = engine.pair_fingerprint(paired_repo.root, pair)
    assert t1 != t2
    assert engine.aggregate_token([t1]) == t1
    assert engine.aggregate_token([t1, t2]) == engine.aggregate_token([t2, t1])


def test_config_weakenings_directions():
    old = ledger.config_snapshot(load_cfg_like(gate="strict", ignore=[], min_length=3))
    new = ledger.config_snapshot(
        load_cfg_like(gate="warn", ignore=["secret_*"], min_length=4, drop_pair=True)
    )
    weak = ledger.config_weakenings(old, new)
    joined = "\n".join(weak)
    assert "strict -> warn" in joined
    assert "pair removed: docs/auth.md" in joined
    assert "anchor ignore added" in joined
    assert "min_length raised" in joined
    # 強化方向は無音
    assert not ledger.config_weakenings(new, new)
    assert not ledger.config_weakenings(old, old)


def load_cfg_like(gate="warn", ignore=None, min_length=3, drop_pair=False):
    from staledocs.config import AnchorRule, Config, PairRule

    cfg = Config()
    cfg.gate = gate
    cfg.source_include = ["src/**"]
    cfg.pairs = [] if drop_pair else [PairRule(doc="docs/auth.md", code=["src/auth/**"])]
    cfg.anchors = AnchorRule(min_length=min_length, ignore=list(ignore or []))
    return cfg


def test_config_weakening_reds_check_until_accepted(paired_repo):
    _ack_all(paired_repo)
    cfg = load(paired_repo.root)
    ledger.write_config_ack(paired_repo.root, ledger.config_snapshot(cfg), note="baseline")
    result = _check(paired_repo)
    assert result.config_weakenings == []
    assert not result.config_baseline_missing

    cfg_path = paired_repo.root / ".staledocs.yaml"
    cfg_path.write_text(
        cfg_path.read_text(encoding="utf-8") + "anchors:\n  ignore: [issue_token]\n",
        encoding="utf-8",
    )
    result = _check(paired_repo)
    assert any("ignore added" in w for w in result.config_weakenings)
    assert result.red_count() >= 1

    # 受け入れ = 新 snapshot を baseline 化 → red 解消
    cfg2 = load(paired_repo.root)
    ledger.write_config_ack(paired_repo.root, ledger.config_snapshot(cfg2), note="accepted")
    result = _check(paired_repo)
    assert result.config_weakenings == []


def test_config_baseline_missing_is_warn_only(paired_repo):
    result = _check(paired_repo)
    assert result.config_baseline_missing
    # baseline 不在は red に数えない (既存 v0.1 導入 repo の upgrade を壊さない)
    assert all("config" not in w for w in result.config_weakenings)


def test_trailer_absorbs_even_when_ack_commit_is_lost(paired_repo):
    # squash merge 後: 台帳の ack.commit が clone に存在しない sha を指す。
    # trailer 走査は全履歴 fallback で吸収し、BROKEN 誤爆しない (= CI 鏡の等価性)。
    _ack_all(paired_repo)
    entry = paired_repo.root / ".staledocs/pairs" / f"{ledger.pair_id('docs/auth.md')}.json"
    import json

    raw = json.loads(entry.read_text(encoding="utf-8"))
    raw["ack"]["commit"] = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    entry.write_text(json.dumps(raw), encoding="utf-8")

    paired_repo.write("src/auth/token.py", "def issue_token(ttl=5):\n    return 'tok'\n")
    paired_repo.write("docs/auth.md", "# Auth\n\n`issue_token` now takes ttl.\n")
    paired_repo.root.joinpath("msg").write_text(
        "sync\n\nStaledocs-Ack: docs/auth.md\n", encoding="utf-8"
    )
    paired_repo.git("add", "-A")
    paired_repo.git("commit", "-F", "msg", "--no-verif" + "y", "--quiet")
    (paired_repo.root / "msg").unlink()
    report = _pair_state(paired_repo)
    assert report.state == engine.GREEN
    assert "trailer" in report.detail


# --- v1.1: doc<->doc chained pairs + init --suggest --------------------------


def _chained_repo(repo):
    """要件定義書 (上流) ← 設計書 (下流) ← コード、の 3 段連鎖 fixture。"""
    repo.write("src/auth/token.py", "def issue_token():\n    return 'tok'\n")
    repo.write("docs/requirements.md", "# Req\n\nToken auth: issue via `issue_token`.\n")
    repo.write(
        "docs/design.md",
        "# Design\n\nImplements `issue_token` per `docs/requirements.md`.\n",
    )
    repo.write(
        ".staledocs.yaml",
        (
            "version: 1\n"
            "gate: warn\n"
            "source:\n"
            "  include: [\"src/**\"]\n"
            "docs:\n"
            "  include: [\"docs/**/*.md\"]\n"
            "pairs:\n"
            "  - doc: docs/design.md\n"
            "    code: [\"src/auth/**\", \"docs/requirements.md\"]\n"
            "  - doc: docs/requirements.md\n"
            "    code: [\"src/auth/**\"]\n"
        ),
    )
    repo.commit("chained fixture")
    return repo


def test_doc_to_doc_pair_resolves(repo):
    _chained_repo(repo)
    from staledocs.config import load
    from staledocs.mapping import resolve

    cfg = load(repo.root)
    mapping = resolve(cfg, gitio.ls_files(repo.root))
    design = next(p for p in mapping.pairs if p.doc == "docs/design.md")
    assert "docs/requirements.md" in design.code_files
    assert "src/auth/token.py" in design.code_files


def test_upstream_doc_move_breaks_downstream_with_line_evidence(repo):
    _chained_repo(repo)
    _ack_all(repo)
    # 上流 (要件) の issue_token に触れる行が動く → 下流 (設計書) が red、行証拠付き
    repo.write(
        "docs/requirements.md", "# Req\n\nToken auth: `issue_token` gains TTL.\n"
    )
    repo.commit("requirement changed", "docs/requirements.md")
    report = _pair_state(repo, doc="docs/design.md")
    assert report.state == engine.DOC_STALE
    hit = next(h for h in report.hit_anchors if h.file == "docs/requirements.md")
    assert hit.kind in ("path", "ident")


def test_doc_never_pairs_to_itself(repo):
    repo.write("docs/design.md", "# D\n")
    repo.write("src/x.py", "pass\n")
    repo.write(
        ".staledocs.yaml",
        (
            "version: 1\n"
            "gate: warn\n"
            "source:\n"
            "  include: [\"src/**\"]\n"
            "docs:\n"
            "  include: [\"docs/**/*.md\"]\n"
            "pairs:\n"
            "  - doc: docs/design.md\n"
            "    code: [\"docs/**\", \"src/**\"]\n"
        ),
    )
    repo.commit("self glob")
    from staledocs.config import load
    from staledocs.mapping import resolve

    cfg = load(repo.root)
    mapping = resolve(cfg, gitio.ls_files(repo.root))
    design = next(p for p in mapping.pairs if p.doc == "docs/design.md")
    assert "docs/design.md" not in design.code_files


def test_suggest_builds_pairs_from_anchors(repo):
    repo.write("src/auth/token.py", "def issue_token():\n    return 1\n")
    repo.write("src/auth/session.py", "def open_session():\n    return 1\n")
    repo.write("src/billing/invoice.py", "def bill():\n    return 1\n")
    repo.write(
        "docs/auth.md", "# Auth\n\n`issue_token` and `open_session` live in `src/auth/`.\n"
    )
    repo.write("docs/notes.md", "# Notes\n\nProse only, no anchors.\n")
    repo.write(
        ".staledocs.yaml",
        (
            "version: 1\n"
            "gate: warn\n"
            "source:\n"
            "  include: [\"src/**\"]\n"
            "docs:\n"
            "  include: [\"docs/**/*.md\"]\n"
        ),
    )
    repo.commit("suggest fixture")
    from staledocs import suggest
    from staledocs.config import load

    cfg = load(repo.root)
    out = suggest.build(repo.root, cfg, gitio.ls_files(repo.root))
    auth = next(s for s in out if s.doc == "docs/auth.md")
    assert "src/auth/**" in auth.patterns  # 全 file 言及 -> dir glob へ集約
    assert "src/billing/invoice.py" not in " ".join(auth.patterns)
    notes = next(s for s in out if s.doc == "docs/notes.md")
    assert notes.patterns == []  # standalone 候補
    text = suggest.render(out)
    assert "docs/auth.md" in text and "standalone" in text


# --- v1.2: executable-docs layer (opt-in, warn-only, no execution) -----------


def _examples_repo(repo, examples_yaml):
    repo.write("src/x.py", "def f():\n    return 1\n")
    repo.write(
        "docs/guide.md",
        "# Guide\n\n```python\n>>> f()\n1\n```\n\nAlso:\n\n"
        "```console\n$ run\nok\n```\n\n```yaml\nkey: v\n```\n",
    )
    repo.write(
        ".staledocs.yaml",
        (
            "version: 1\n"
            "gate: warn\n"
            "source:\n"
            "  include: [\"src/**\"]\n"
            "docs:\n"
            "  include: [\"docs/**/*.md\"]\n"
            "pairs:\n"
            "  - doc: docs/guide.md\n"
            "    code: [\"src/**\"]\n"
            + examples_yaml
        ),
    )
    repo.commit("examples fixture")
    return repo


def test_examples_layer_off_when_undeclared(repo):
    _examples_repo(repo, "")
    result = _check(repo)
    assert result.examples is None  # opt-in: 完全沈黙


def test_examples_inventory_and_undeclared_warn(repo):
    _examples_repo(
        repo,
        "examples:\n  python: \"pytest --doctest-glob\"\n  yaml: none\n",
    )
    result = _check(repo)
    ex = result.examples
    assert ex.enabled
    assert ex.wired == {"python": 1}
    assert ex.per_doc == {"docs/guide.md": 1}
    # console は未分類 -> warn 対象。yaml は none 宣言済みで沈黙
    tags = [b.tag for b in ex.undeclared]
    assert tags == ["console"]
    # warn-only: red には数えない
    assert result.red_count() == 1  # UNACKED pair のみ


def test_examples_unwiring_is_a_config_weakening(repo):
    _examples_repo(repo, "examples:\n  python: \"pytest\"\n")
    from staledocs.config import load

    old = ledger.config_snapshot(load(repo.root))
    cfg_path = repo.root / ".staledocs.yaml"
    text = cfg_path.read_text(encoding="utf-8")
    cfg_path.write_text(text.replace('  python: "pytest"', "  python: none"), encoding="utf-8")
    new = ledger.config_snapshot(load(repo.root))
    weak = ledger.config_weakenings(old, new)
    assert any("example runner unwired" in w for w in weak)


def test_examples_scan_ignores_closing_fences_and_untagged(repo):
    from staledocs import examples

    blocks = examples.scan_doc(
        "d.md",
        "```python\ncode\n```\n\n```\nplain\n```\n\n~~~sh\nx\n~~~\n",
    )
    assert [(b.tag, b.line) for b in blocks] == [("python", 1), ("sh", 9)]


def test_old_trailer_on_parallel_leg_does_not_roll_back_the_baseline(paired_repo):
    # merge topology + squash-era trailer: a leg joined by a merge carries an
    # OLD Staledocs-Ack (a past release commit). `since..HEAD` surfaces that
    # leg, but only a descendant of the acked commit may advance the baseline
    # — absorbing the old trailer would roll the pair back to a stale state.
    base = paired_repo.git("rev-parse", "HEAD").strip()

    # parallel leg: an old trailer ack recorded when the doc was older
    paired_repo.git("checkout", "-b", "legacy", base, "--quiet")
    paired_repo.root.joinpath("msg").write_text(
        "old release\n\nStaledocs-Ack: docs/auth.md\n", encoding="utf-8"
    )
    paired_repo.write("legacy-note.txt", "x\n")
    paired_repo.git("add", "-A")
    paired_repo.git("commit", "-F", "msg", "--no-verify", "--quiet")
    (paired_repo.root / "msg").unlink()

    # mainline: doc and code evolve together, then a fresh CLI ack
    paired_repo.git("checkout", "main", "--quiet")
    paired_repo.write("src/auth/token.py", "def issue_token(ttl=90):\n    return 'tok'\n")
    paired_repo.write("docs/auth.md", "# Auth\n\nTTL 90 documented in `src/auth/token.py`.\n")
    paired_repo.commit("evolve both")
    _ack_all(paired_repo)

    # the merge joins the legacy leg into mainline history
    paired_repo.git("merge", "legacy", "--no-ff", "--no-verify", "--quiet",
                    "-m", "join legacy leg")

    report = _pair_state(paired_repo)
    assert report.state == engine.GREEN  # ledger ack stands; old trailer skipped
    assert "trailer" not in (report.detail or "")
