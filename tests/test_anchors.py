from pathlib import Path

from staledocs import anchors
from staledocs.anchors import CodeIndex
from staledocs.config import AnchorRule

RULE = AnchorRule(min_length=3, ignore=[], include_fenced=False)


def _tokens(text: str, rule: AnchorRule = RULE) -> list[str]:
    return [a.token for a in anchors.extract("d.md", text, rule)]


def test_extracts_code_like_tokens_only():
    text = "Call `issue_token()` with `MAX_RETRIES` but not `plain words here` or `and`.\n"
    assert _tokens(text) == ["issue_token()", "MAX_RETRIES"]


def test_camel_case_and_flags_count_as_code():
    text = "`parseConfig` handles `--dry-run` and `-v` flags.\n"
    assert _tokens(text) == ["parseConfig", "--dry-run"]


def test_fenced_blocks_skipped_by_default():
    text = "```python\n`inside_fence()`\ncall_here()\n```\nOutside `real_anchor()`.\n"
    assert _tokens(text) == ["real_anchor()"]


def test_fenced_blocks_included_when_opted_in():
    rule = AnchorRule(min_length=3, ignore=[], include_fenced=True)
    text = "```\n`inside_fence()`\n```\n"
    assert _tokens(text, rule) == ["inside_fence()"]


def test_ignore_list_and_min_length():
    rule = AnchorRule(min_length=6, ignore=["skip_me()"], include_fenced=False)
    text = "`skip_me()` `a()` `long_enough()`\n"
    assert _tokens(text, rule) == ["long_enough()"]


def test_path_like_detection():
    got = anchors.extract("d.md", "See `src/auth/token.py` and `issue_token`.\n", RULE)
    assert [(a.token, a.path_like) for a in got] == [
        ("src/auth/token.py", True),
        ("issue_token", False),
    ]


def test_urls_are_not_extracted(tmp_path: Path):
    got = anchors.extract("d.md", "Visit `https://example.com/x`.\n", RULE)
    assert got == []


def test_verify_identifier_against_pair_scope(tmp_path: Path):
    (tmp_path / "a.py").write_text("def issue_token():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def gone_elsewhere():\n    pass\n", encoding="utf-8")
    found = anchors.extract("d.md", "`issue_token` and `gone_fn` live here.\n", RULE)
    pair_index = CodeIndex(tmp_path, ["a.py"])
    repo_index = CodeIndex(tmp_path, ["a.py", "b.py"])
    findings = anchors.verify(
        tmp_path, "d.md", found, pair_index, repo_index, set(), set()
    )
    assert [(f.token, f.scope) for f in findings] == [("gone_fn", "pair")]


def test_pair_scope_prevents_false_pass_from_other_files(tmp_path: Path):
    # the identifier survives elsewhere in the repo but left the paired code —
    # repo-wide grep would mask it, pair scope must flag it
    (tmp_path / "a.py").write_text("def other():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def moved_away():\n    pass\n", encoding="utf-8")
    found = anchors.extract("d.md", "`moved_away` is documented here.\n", RULE)
    pair_index = CodeIndex(tmp_path, ["a.py"])
    repo_index = CodeIndex(tmp_path, ["a.py", "b.py"])
    findings = anchors.verify(tmp_path, "d.md", found, pair_index, repo_index, set(), set())
    assert [f.token for f in findings] == ["moved_away"]


def test_path_anchor_verifies_against_file_tree(tmp_path: Path):
    found = anchors.extract("d.md", "See `src/real.py` and `src/gone.py`.\n", RULE)
    files = {"src/real.py"}
    findings = anchors.verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []), files, anchors.dirs_of(files)
    )
    assert [f.token for f in findings] == ["src/gone.py"]


def test_directory_path_anchor_ok(tmp_path: Path):
    found = anchors.extract("d.md", "Everything under `src/auth/`.\n", RULE)
    files = {"src/auth/token.py"}
    findings = anchors.verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []), files, anchors.dirs_of(files)
    )
    assert findings == []


def test_glob_path_anchor(tmp_path: Path):
    found = anchors.extract("d.md", "Matches `src/*.py` and `lib/*.py`.\n", RULE)
    files = {"src/a.py"}
    findings = anchors.verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []), files, anchors.dirs_of(files)
    )
    assert [f.token for f in findings] == ["lib/*.py"]


def test_placeholder_notation_skipped():
    text = "See `docs/<name>.md` and `<slug>-<sha>.json` and `pairs[].doc`.\n"
    # <...> placeholders are not anchors; bracket notation without <> still is
    assert _tokens(text) == ["pairs[].doc"]


def test_bare_filename_resolves_via_file_tree(tmp_path: Path):
    found = anchors.extract("d.md", "See `README.ja.md` for Japanese.\n", RULE)
    files = {"README.ja.md"}
    findings = anchors.verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []), files, anchors.dirs_of(files)
    )
    assert findings == []


def test_dotted_identifier_falls_back_to_last_segment(tmp_path: Path):
    (tmp_path / "a.py").write_text("include_fenced = False\n", encoding="utf-8")
    found = anchors.extract("d.md", "`anchors.include_fenced` toggles fences.\n", RULE)
    idx = CodeIndex(tmp_path, ["a.py"])
    findings = anchors.verify(tmp_path, "d.md", found, idx, idx, set(), set())
    assert findings == []


def test_machine_absolute_paths_skipped():
    text = "Config lives in `~/.config/tool/` and `/usr/local/bin/tool`.\n"
    assert _tokens(text) == []


def test_path_roots_resolve_subtree_relative_paths(tmp_path: Path):
    found = anchors.extract("d.md", "See `rules/always.md` in the payload.\n", RULE)
    files = {"src/rules/always.md"}
    findings = anchors.verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []),
        files, anchors.dirs_of(files), path_roots=["src"],
    )
    assert findings == []


def test_path_roots_do_not_mask_real_dead_paths(tmp_path: Path):
    found = anchors.extract("d.md", "See `rules/gone.md` here.\n", RULE)
    files = {"src/rules/always.md"}
    findings = anchors.verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []),
        files, anchors.dirs_of(files), path_roots=["src"],
    )
    assert [f.token for f in findings] == ["rules/gone.md"]


def test_path_roots_with_glob_tokens(tmp_path: Path):
    found = anchors.extract("d.md", "All of `rules/lazy/*.md` apply.\n", RULE)
    files = {"src/rules/lazy/one.md"}
    findings = anchors.verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []),
        files, anchors.dirs_of(files), path_roots=["src"],
    )
    assert findings == []


def test_gitignored_path_anchor_passes(tmp_path: Path):
    found = anchors.extract("d.md", "Logs land in `logs/backend.log` locally.\n", RULE)
    ignored = lambda cands: {c for c in cands if c.startswith("logs/")}  # noqa: E731
    findings = anchors.verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []),
        set(), set(), check_ignored=ignored,
    )
    assert findings == []


def test_unignored_missing_path_still_flags(tmp_path: Path):
    found = anchors.extract("d.md", "See `src/gone.py` here.\n", RULE)
    findings = anchors.verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []),
        set(), set(), check_ignored=lambda c: set(),
    )
    assert [f.token for f in findings] == ["src/gone.py"]


def test_path_symbol_anchor(tmp_path: Path):
    (tmp_path / "mod.py").write_text("_DENY_RE = 1\n", encoding="utf-8")
    text = "Guard lives at `mod.py::_DENY_RE` and `mod.py::GONE_SYMBOL`.\n"
    found = anchors.extract("d.md", text, RULE)
    findings = anchors.verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []),
        {"mod.py"}, set(),
    )
    assert [f.token for f in findings] == ["mod.py::GONE_SYMBOL"]


def test_slashless_glob_matches_basenames(tmp_path: Path):
    found = anchors.extract("d.md", "Sharpen a `detect-*` script.\n", RULE)
    files = {"src/.tooling/detect-stale.sh"}
    findings = anchors.verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []),
        files, anchors.dirs_of(files),
    )
    assert findings == []


def test_digit_heavy_and_art_tokens_skipped():
    text = "Shows `7d:53%` and `ctx:███░░░░░35%` and `5h:24%(3h22m)`.\n"
    assert _tokens(text) == []


def test_shell_var_tokens_skipped():
    text = "Word list at `$HOME/.config/anon-words/master.txt`.\n"
    assert _tokens(text) == []


def test_doc_relative_path_resolution(tmp_path: Path):
    text = "See `../protocol/streams.md` and `launchd/x.plist`.\n"
    found = anchors.extract("docs/setup/guide.md", text, RULE)
    files = {"docs/protocol/streams.md", "docs/setup/launchd/x.plist"}
    findings = anchors.verify(
        tmp_path, "docs/setup/guide.md", found, None, CodeIndex(tmp_path, []),
        files, anchors.dirs_of(files),
    )
    assert findings == []


def test_doc_relative_does_not_mask_dead_links(tmp_path: Path):
    found = anchors.extract("docs/setup/guide.md", "See `../gone/nothing.md`.\n", RULE)
    files = {"docs/setup/guide.md"}
    findings = anchors.verify(
        tmp_path, "docs/setup/guide.md", found, None, CodeIndex(tmp_path, []),
        files, anchors.dirs_of(files),
    )
    assert [f.token for f in findings] == ["../gone/nothing.md"]


def test_call_and_subscript_notation_falls_back_to_bare_name(tmp_path: Path):
    (tmp_path / "a.js").write_text(
        "const loading = {}; function truncate(s) {}; let viewMode = 'x';\n",
        encoding="utf-8",
    )
    text = "`truncate()` and `loading[sid]` and `viewMode='terminal'` work.\n"
    found = anchors.extract("d.md", text, RULE)
    idx = CodeIndex(tmp_path, ["a.js"])
    findings = anchors.verify(tmp_path, "d.md", found, idx, idx, set(), set())
    assert findings == []


def test_glob_identifier_prefix_greps(tmp_path: Path):
    (tmp_path / "a.py").write_text('emit("system_init")\n', encoding="utf-8")
    found = anchors.extract("d.md", "Events named `system_*` fan out.\n", RULE)
    idx = CodeIndex(tmp_path, ["a.py"])
    findings = anchors.verify(tmp_path, "d.md", found, idx, idx, set(), set())
    assert findings == []


def test_symbol_anchor_into_gitignored_file_passes(tmp_path: Path):
    found = anchors.extract("d.md", "Set `config.json::agents` locally.\n", RULE)
    ignored = lambda cands: {c for c in cands if c.startswith("config.json")}  # noqa: E731
    findings = anchors.verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []),
        set(), set(), check_ignored=ignored,
    )
    assert findings == []


def test_call_notation_with_slash_in_args_is_not_a_path(tmp_path: Path):
    # `exp(−d/λ)` — a formula quoted in a design doc. The slash lives inside
    # the call arguments; the path branch must not capture the token before
    # the bare-identifier fallback (field-reported: the whole token went red
    # while the reference promised the `exp` fallback).
    (tmp_path / "model.py").write_text("import numpy as np\np = np.exp(-d)\n", encoding="utf-8")
    text = "Connection probability decays as `exp(−d/λ)` with distance.\n"
    found = anchors.extract("d.md", text, RULE)
    assert [(a.token, a.path_like) for a in found] == [("exp(−d/λ)", False)]
    idx = CodeIndex(tmp_path, ["model.py"])
    findings = anchors.verify(tmp_path, "d.md", found, idx, idx, set(), set())
    assert findings == []


def test_path_with_parens_after_slash_stays_a_path():
    # a genuine path whose later segment contains parens keeps path semantics
    got = anchors.extract("d.md", "Kept under `src/legacy/util(old).py` for now.\n", RULE)
    assert [(a.token, a.path_like) for a in got] == [("src/legacy/util(old).py", True)]


def test_branch_prefix_token_skips_path_verification(tmp_path: Path):
    # `feature/dark-mode` is a quoted branch name, not a rotted path
    found = anchors.extract("d.md", "Cut `feature/dark-mode` from develop.\n", RULE)
    idx = CodeIndex(tmp_path, [])
    findings = anchors.verify(
        tmp_path, "d.md", found, idx, idx, set(), set(),
        branch_prefixes=["feature", "fix"],
    )
    assert findings == []


def test_branch_prefix_skip_disabled_with_empty_list(tmp_path: Path):
    found = anchors.extract("d.md", "Cut `feature/dark-mode` from develop.\n", RULE)
    idx = CodeIndex(tmp_path, [])
    findings = anchors.verify(
        tmp_path, "d.md", found, idx, idx, set(), set(), branch_prefixes=[],
    )
    assert [f.token for f in findings] == ["feature/dark-mode"]


def test_tracked_path_under_branch_prefix_dir_still_verifies(tmp_path: Path):
    # a repo genuinely containing a feature/ dir: existing paths pass on the
    # tree, dead paths under it are skipped only because the prefix matches —
    # the tracked-file check runs first either way
    files = {"feature/flags.py"}
    found = anchors.extract("d.md", "See `feature/flags.py`.\n", RULE)
    idx = CodeIndex(tmp_path, [])
    findings = anchors.verify(
        tmp_path, "d.md", found, idx, idx, files, anchors.dirs_of(files),
        branch_prefixes=["feature"],
    )
    assert findings == []


def test_ignore_entry_with_glob_chars_covers_the_family(tmp_path: Path):
    rule = AnchorRule(min_length=3, ignore=["research/*"])
    text = "See `research/01-intro.md` and `research/10-close.md`.\n"
    found = anchors.extract("d.md", text, rule)
    assert found == []


def test_ignore_glob_entry_still_suppresses_its_own_literal_token(tmp_path: Path):
    # an entry written as an exact token before glob support existed must
    # keep suppressing the literal token itself (exact stage runs first)
    rule = AnchorRule(min_length=3, ignore=["com.example.*"])
    found = anchors.extract("d.md", "Bundle id prefix `com.example.*` is ours.\n", rule)
    assert found == []


def test_ignore_literal_entry_stays_exact(tmp_path: Path):
    # no glob characters -> exact only; a sibling token is still extracted
    rule = AnchorRule(min_length=3, ignore=["issue_token"])
    found = anchors.extract("d.md", "`issue_token` and `open_session` here.\n", rule)
    assert [a.token for a in found] == ["open_session"]
