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


def test_urls_are_not_path_like_and_not_findings(tmp_path: Path):
    got = anchors.extract("d.md", "Visit `https://example.com/x`.\n", RULE)
    assert got and not got[0].path_like


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
