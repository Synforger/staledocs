from pathlib import Path

from staledocs import anchors
from staledocs.anchors import CodeIndex
from staledocs.config import AnchorRule

RULE = AnchorRule(min_length=3, ignore=[], include_fenced=False)

def _verify(repo_root, doc, found, pair_index, repo_index, all_files, all_dirs,
            path_roots=None, check_ignored=None, branch_prefixes=None, skipped=None):
    """Old-signature shim: arms every claim, so these tests exercise the
    resolver itself (baseline semantics are tested separately below)."""
    ctx = anchors.ResolveCtx(
        repo_root=repo_root, pair_index=pair_index, repo_index=repo_index,
        all_files=all_files, all_dirs=all_dirs, path_roots=path_roots,
        check_ignored=check_ignored, branch_prefixes=branch_prefixes,
    )
    baseline = set()
    for a in found:
        if a.planned:
            continue
        for key, _ok in anchors._claims(a, ctx):
            baseline.add(key)
    findings, _status = anchors.verify(doc, found, baseline, ctx)
    return findings




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
    findings = _verify(
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
    findings = _verify(tmp_path, "d.md", found, pair_index, repo_index, set(), set())
    assert [f.token for f in findings] == ["moved_away"]


def test_path_anchor_verifies_against_file_tree(tmp_path: Path):
    found = anchors.extract("d.md", "See `src/real.py` and `src/gone.py`.\n", RULE)
    files = {"src/real.py"}
    findings = _verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []), files, anchors.dirs_of(files)
    )
    assert [f.token for f in findings] == ["src/gone.py"]


def test_directory_path_anchor_ok(tmp_path: Path):
    found = anchors.extract("d.md", "Everything under `src/auth/`.\n", RULE)
    files = {"src/auth/token.py"}
    findings = _verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []), files, anchors.dirs_of(files)
    )
    assert findings == []


def test_glob_path_anchor(tmp_path: Path):
    found = anchors.extract("d.md", "Matches `src/*.py` and `lib/*.py`.\n", RULE)
    files = {"src/a.py"}
    findings = _verify(
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
    findings = _verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []), files, anchors.dirs_of(files)
    )
    assert findings == []


def test_dotted_identifier_falls_back_to_last_segment(tmp_path: Path):
    (tmp_path / "a.py").write_text("include_fenced = False\n", encoding="utf-8")
    found = anchors.extract("d.md", "`anchors.include_fenced` toggles fences.\n", RULE)
    idx = CodeIndex(tmp_path, ["a.py"])
    findings = _verify(tmp_path, "d.md", found, idx, idx, set(), set())
    assert findings == []


def test_machine_absolute_paths_skipped():
    text = "Config lives in `~/.config/tool/` and `/usr/local/bin/tool`.\n"
    assert _tokens(text) == []


def test_path_roots_resolve_subtree_relative_paths(tmp_path: Path):
    found = anchors.extract("d.md", "See `rules/always.md` in the payload.\n", RULE)
    files = {"src/rules/always.md"}
    findings = _verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []),
        files, anchors.dirs_of(files), path_roots=["src"],
    )
    assert findings == []


def test_path_roots_do_not_mask_real_dead_paths(tmp_path: Path):
    found = anchors.extract("d.md", "See `rules/gone.md` here.\n", RULE)
    files = {"src/rules/always.md"}
    findings = _verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []),
        files, anchors.dirs_of(files), path_roots=["src"],
    )
    assert [f.token for f in findings] == ["rules/gone.md"]


def test_path_roots_with_glob_tokens(tmp_path: Path):
    found = anchors.extract("d.md", "All of `rules/lazy/*.md` apply.\n", RULE)
    files = {"src/rules/lazy/one.md"}
    findings = _verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []),
        files, anchors.dirs_of(files), path_roots=["src"],
    )
    assert findings == []


def test_gitignored_path_anchor_passes(tmp_path: Path):
    found = anchors.extract("d.md", "Logs land in `logs/backend.log` locally.\n", RULE)
    ignored = lambda cands: {c for c in cands if c.startswith("logs/")}  # noqa: E731
    findings = _verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []),
        set(), set(), check_ignored=ignored,
    )
    assert findings == []


def test_unignored_missing_path_still_flags(tmp_path: Path):
    found = anchors.extract("d.md", "See `src/gone.py` here.\n", RULE)
    findings = _verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []),
        set(), set(), check_ignored=lambda c: set(),
    )
    assert [f.token for f in findings] == ["src/gone.py"]


def test_path_symbol_anchor(tmp_path: Path):
    (tmp_path / "mod.py").write_text("_DENY_RE = 1\n", encoding="utf-8")
    text = "Guard lives at `mod.py::_DENY_RE` and `mod.py::GONE_SYMBOL`.\n"
    found = anchors.extract("d.md", text, RULE)
    findings = _verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []),
        {"mod.py"}, set(),
    )
    assert [f.token for f in findings] == ["mod.py::GONE_SYMBOL"]


def test_slashless_glob_matches_basenames(tmp_path: Path):
    found = anchors.extract("d.md", "Sharpen a `detect-*` script.\n", RULE)
    files = {"src/.tooling/detect-stale.sh"}
    findings = _verify(
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
    findings = _verify(
        tmp_path, "docs/setup/guide.md", found, None, CodeIndex(tmp_path, []),
        files, anchors.dirs_of(files),
    )
    assert findings == []


def test_doc_relative_does_not_mask_dead_links(tmp_path: Path):
    found = anchors.extract("docs/setup/guide.md", "See `../gone/nothing.md`.\n", RULE)
    files = {"docs/setup/guide.md"}
    findings = _verify(
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
    findings = _verify(tmp_path, "d.md", found, idx, idx, set(), set())
    assert findings == []


def test_glob_identifier_prefix_greps(tmp_path: Path):
    (tmp_path / "a.py").write_text('emit("system_init")\n', encoding="utf-8")
    found = anchors.extract("d.md", "Events named `system_*` fan out.\n", RULE)
    idx = CodeIndex(tmp_path, ["a.py"])
    findings = _verify(tmp_path, "d.md", found, idx, idx, set(), set())
    assert findings == []


def test_symbol_anchor_into_gitignored_file_passes(tmp_path: Path):
    found = anchors.extract("d.md", "Set `config.json::agents` locally.\n", RULE)
    ignored = lambda cands: {c for c in cands if c.startswith("config.json")}  # noqa: E731
    findings = _verify(
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
    findings = _verify(tmp_path, "d.md", found, idx, idx, set(), set())
    assert findings == []


def test_path_with_parens_after_slash_stays_a_path():
    # a genuine path whose later segment contains parens keeps path semantics
    got = anchors.extract("d.md", "Kept under `src/legacy/util(old).py` for now.\n", RULE)
    assert [(a.token, a.path_like) for a in got] == [("src/legacy/util(old).py", True)]


def test_branch_prefix_token_skips_path_verification(tmp_path: Path):
    # `feature/dark-mode` is a quoted branch name, not a rotted path
    found = anchors.extract("d.md", "Cut `feature/dark-mode` from develop.\n", RULE)
    idx = CodeIndex(tmp_path, [])
    findings = _verify(
        tmp_path, "d.md", found, idx, idx, set(), set(),
        branch_prefixes=["feature", "fix"],
    )
    assert findings == []


def test_branch_prefix_skip_disabled_with_empty_list(tmp_path: Path):
    found = anchors.extract("d.md", "Cut `feature/dark-mode` from develop.\n", RULE)
    idx = CodeIndex(tmp_path, [])
    findings = _verify(
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
    findings = _verify(
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


def test_assignment_with_absolute_path_value_falls_back_to_bare_name(tmp_path: Path):
    # `TOOL_PATH=/usr/bin/tool` quoted in a setup doc: the slash lives in the
    # assigned value; the token is assignment notation and falls back to the
    # variable name, which is what the paired code actually contains
    (tmp_path / "conf.py").write_text('TOOL_PATH = os.environ["TOOL_PATH"]\n', encoding="utf-8")
    found = anchors.extract("d.md", "Set `TOOL_PATH=/usr/bin/tool` for tests.\n", RULE)
    assert [(a.token, a.path_like) for a in found] == [("TOOL_PATH=/usr/bin/tool", False)]
    idx = CodeIndex(tmp_path, ["conf.py"])
    findings = _verify(tmp_path, "d.md", found, idx, idx, set(), set())
    assert findings == []


def test_assignment_to_unknown_variable_still_reds_on_the_bare_name(tmp_path: Path):
    (tmp_path / "conf.py").write_text("OTHER = 1\n", encoding="utf-8")
    found = anchors.extract("d.md", "Set `GONE_VAR=/usr/bin/tool` for tests.\n", RULE)
    idx = CodeIndex(tmp_path, ["conf.py"])
    findings = _verify(tmp_path, "d.md", found, idx, idx, set(), set())
    assert [f.token for f in findings] == ["GONE_VAR=/usr/bin/tool"]


def test_path_with_equals_after_slash_stays_a_path():
    # query-ish or annotated path where `=` appears past the first slash
    got = anchors.extract("d.md", "See `docs/api?v=2` notes.\n", RULE)
    assert [(a.token, a.path_like) for a in got] == [("docs/api?v=2", True)]


def test_brace_expansion_reports_only_missing_members(tmp_path: Path):
    found = anchors.extract("d.md", "See `src/{real,gone}.py`.\n", RULE)
    files = {"src/real.py"}
    findings = _verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []), files, anchors.dirs_of(files)
    )
    assert [f.token for f in findings] == ["src/gone.py"]


def test_brace_expansion_passes_when_all_members_exist(tmp_path: Path):
    found = anchors.extract("d.md", "Bridges: `bridge/{diag,logger}.cjs`.\n", RULE)
    files = {"bridge/diag.cjs", "bridge/logger.cjs"}
    findings = _verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []), files, anchors.dirs_of(files)
    )
    assert findings == []


def test_brace_without_comma_stays_literal(tmp_path: Path):
    found = anchors.extract("d.md", "Uses `src/{name}/mod.py` layout.\n", RULE)
    files = {"src/auth/mod.py"}
    findings = _verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []), files, anchors.dirs_of(files)
    )
    assert [f.token for f in findings] == ["src/{name}/mod.py"]


def test_expand_braces_multiple_groups():
    got = anchors.expand_braces("a/{x,y}/b.{md,py}")
    assert got == ["a/x/b.md", "a/x/b.py", "a/y/b.md", "a/y/b.py"]


def test_planned_marker_pending_and_resolved(tmp_path: Path):
    text = "Will land in `planned:src/future.py`; already here: `planned:src/real.py`.\n"
    found = anchors.extract("d.md", text, RULE)
    assert [(a.token, a.planned) for a in found] == [
        ("src/future.py", True),
        ("src/real.py", True),
    ]
    files = {"src/real.py"}
    findings = _verify(
        tmp_path, "d.md", found, None, CodeIndex(tmp_path, []), files, anchors.dirs_of(files)
    )
    assert [(f.token, f.planned) for f in findings] == [
        ("src/future.py", "pending"),
        ("src/real.py", "resolved"),
    ]


def test_unresolved_tokens_are_unarmed_not_red(tmp_path: Path):
    # record() arms only proven claims; prose and junk never enter the
    # baseline, so they can never red — but they are counted, not silent
    text = "Clamp to `min/max` values; see `src/real.py` and `src/gone.py`.\n"
    found = anchors.extract("d.md", text, RULE)
    files = {"src/real.py"}
    ctx = anchors.ResolveCtx(
        repo_root=tmp_path, pair_index=None, repo_index=CodeIndex(tmp_path, []),
        all_files=files, all_dirs=anchors.dirs_of(files),
    )
    baseline = anchors.record(found, ctx)
    assert baseline == ["src/real.py"]
    findings, status = anchors.verify("d.md", found, set(baseline), ctx)
    assert findings == []
    assert status.armed == 1
    assert sorted(status.unarmed_tokens) == ["min/max", "src/gone.py"]


def test_armed_claim_that_stops_resolving_is_red(tmp_path: Path):
    found = anchors.extract("d.md", "See `src/real.py`.\n", RULE)
    files_then = {"src/real.py"}
    ctx_then = anchors.ResolveCtx(
        repo_root=tmp_path, pair_index=None, repo_index=CodeIndex(tmp_path, []),
        all_files=files_then, all_dirs=anchors.dirs_of(files_then),
    )
    baseline = set(anchors.record(found, ctx_then))
    ctx_now = anchors.ResolveCtx(
        repo_root=tmp_path, pair_index=None, repo_index=CodeIndex(tmp_path, []),
        all_files=set(), all_dirs=set(),
    )
    findings, _status = anchors.verify("d.md", found, baseline, ctx_now)
    assert [f.token for f in findings] == ["src/real.py"]


def test_suffix_resolution_arms_module_relative_paths(tmp_path: Path):
    # docs quote paths relative to their subtree: `core/Foo.ts` resolves
    # when a tracked path ends with /core/Foo.ts
    found = anchors.extract("d.md", "Implemented in `core/Foo.ts`.\n", RULE)
    files = {"sdk/modules/x/src/core/Foo.ts"}
    ctx = anchors.ResolveCtx(
        repo_root=tmp_path, pair_index=None, repo_index=CodeIndex(tmp_path, []),
        all_files=files, all_dirs=anchors.dirs_of(files),
    )
    assert anchors.record(found, ctx) == ["core/Foo.ts"]
    findings, _ = anchors.verify("d.md", found, {"core/Foo.ts"}, ctx)
    assert findings == []


def test_dotted_bare_filename_resolves_by_basename(tmp_path: Path):
    found = anchors.extract("d.md", "The header `dsp.h` and gone `nope.h`.\n", RULE)
    files = {"sdk/include/dsp.h"}
    ctx = anchors.ResolveCtx(
        repo_root=tmp_path, pair_index=None, repo_index=CodeIndex(tmp_path, []),
        all_files=files, all_dirs=anchors.dirs_of(files),
    )
    assert anchors.record(found, ctx) == ["dsp.h"]


def test_package_specifier_verifies_as_identifier(tmp_path: Path):
    # `@scope/pkg` is a package specifier: import statements quote it
    # verbatim, so it greps the paired code instead of the file tree
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.ts").write_text('import { x } from "@acme/sdk";\n')
    found = anchors.extract("d.md", "Depends on `@acme/sdk` and `@acme/gone`.\n", RULE)
    assert [(a.token, a.path_like) for a in found] == [
        ("@acme/sdk", False),
        ("@acme/gone", False),
    ]
    pair_index = CodeIndex(tmp_path, ["src/app.ts"])
    findings = _verify(
        tmp_path, "d.md", found, pair_index, CodeIndex(tmp_path, []), set(), set()
    )
    assert [(f.token, f.scope) for f in findings] == [("@acme/gone", "pair")]


def test_package_subpath_specifier_greps_verbatim(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.ts").write_text('import y from "@acme/sdk/dist/env";\n')
    found = anchors.extract("d.md", "Uses `@acme/sdk/dist/env`.\n", RULE)
    pair_index = CodeIndex(tmp_path, ["src/app.ts"])
    findings = _verify(
        tmp_path, "d.md", found, pair_index, CodeIndex(tmp_path, []), set(), set()
    )
    assert findings == []


def test_pair_miss_hint_names_where_the_identifier_lives(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/auth.py").write_text("def open_session():\n    pass\n")
    (tmp_path / "src/other.py").write_text("def issue_token():\n    pass\n")
    found = anchors.extract("d.md", "Uses `issue_token` heavily.\n", RULE)
    pair_index = CodeIndex(tmp_path, ["src/auth.py"])
    repo_index = CodeIndex(tmp_path, ["src/auth.py", "src/other.py"])
    findings = _verify(
        tmp_path, "d.md", found, pair_index, repo_index, set(), set()
    )
    # still red — a same-named survivor elsewhere never softens the signal
    assert [(f.token, f.scope) for f in findings] == [("issue_token", "pair")]
    assert "exists in src/other.py" in findings[0].hint


def test_pair_miss_with_no_survivor_has_no_hint(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/auth.py").write_text("def open_session():\n    pass\n")
    found = anchors.extract("d.md", "Uses `issue_token` heavily.\n", RULE)
    pair_index = CodeIndex(tmp_path, ["src/auth.py"])
    repo_index = CodeIndex(tmp_path, ["src/auth.py"])
    findings = _verify(
        tmp_path, "d.md", found, pair_index, repo_index, set(), set()
    )
    assert findings[0].hint == ""
