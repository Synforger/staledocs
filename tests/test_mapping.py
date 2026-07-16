from staledocs.config import AnchorRule, Config, MirrorRule, PairRule
from staledocs.mapping import resolve


def _cfg(**kw) -> Config:
    base = dict(
        gate="warn",
        source_include=["src/**"],
        source_exclude=[],
        docs_include=["docs/**/*.md", "README.md"],
        docs_exclude=[],
        pairs=[],
        mirror=MirrorRule(),
        standalone=[],
        global_docs=[],
        anchors=AnchorRule(),
    )
    base.update(kw)
    return Config(**base)


FILES = [
    "README.md",
    "docs/auth.md",
    "docs/ops/runbook.md",
    "docs/orphan.md",
    "src/auth/token.py",
    "src/auth/session.py",
    "src/billing/invoice.py",
]


def test_explicit_pair_resolves_files():
    cfg = _cfg(pairs=[PairRule(doc="docs/auth.md", code=["src/auth/**"])])
    r = resolve(cfg, FILES)
    pair = next(p for p in r.pairs if p.doc == "docs/auth.md")
    assert pair.code_files == ["src/auth/session.py", "src/auth/token.py"]
    assert pair.origin == "explicit"


def test_uncovered_source_is_a_finding():
    cfg = _cfg(pairs=[PairRule(doc="docs/auth.md", code=["src/auth/**"])])
    r = resolve(cfg, FILES)
    assert "src/billing/invoice.py" in r.uncovered_source


def test_unclassified_doc_is_a_finding():
    cfg = _cfg(pairs=[PairRule(doc="docs/auth.md", code=["src/auth/**"])])
    r = resolve(cfg, FILES)
    assert "docs/orphan.md" in r.unclassified_docs
    assert "docs/ops/runbook.md" in r.unclassified_docs


def test_standalone_and_global_classification():
    cfg = _cfg(
        pairs=[PairRule(doc="docs/auth.md", code=["src/auth/**"])],
        standalone=["docs/ops/**"],
        global_docs=["README.md"],
    )
    r = resolve(cfg, FILES)
    assert r.standalone_docs == ["docs/ops/runbook.md"]
    assert r.global_docs == ["README.md"]
    assert r.unclassified_docs == ["docs/orphan.md"]


def test_orphan_pair_when_globs_match_nothing():
    cfg = _cfg(pairs=[PairRule(doc="docs/auth.md", code=["src/nonexistent/**"])])
    r = resolve(cfg, FILES)
    assert r.orphan_pairs == ["docs/auth.md"]


def test_dead_pair_doc_when_doc_missing():
    cfg = _cfg(pairs=[PairRule(doc="docs/gone.md", code=["src/auth/**"])])
    r = resolve(cfg, FILES)
    assert r.dead_pair_docs == ["docs/gone.md"]
    assert all(p.doc != "docs/gone.md" for p in r.pairs)


def test_mirror_pairs_folder_and_file_stem():
    cfg = _cfg(mirror=MirrorRule(enabled=True, docs_root="docs", code_roots=["src"]))
    r = resolve(cfg, FILES)
    auth = next(p for p in r.pairs if p.doc == "docs/auth.md")
    assert auth.origin == "mirror"
    assert auth.code_files == ["src/auth/session.py", "src/auth/token.py"]


def test_explicit_pair_wins_over_mirror():
    cfg = _cfg(
        pairs=[PairRule(doc="docs/auth.md", code=["src/billing/**"])],
        mirror=MirrorRule(enabled=True),
    )
    r = resolve(cfg, FILES)
    auth = [p for p in r.pairs if p.doc == "docs/auth.md"]
    assert len(auth) == 1
    assert auth[0].origin == "explicit"
    assert auth[0].code_files == ["src/billing/invoice.py"]


def test_nm_mapping_one_file_two_docs():
    cfg = _cfg(
        pairs=[
            PairRule(doc="docs/auth.md", code=["src/auth/**"]),
            PairRule(doc="docs/ops/runbook.md", code=["src/auth/session.py"]),
        ]
    )
    r = resolve(cfg, FILES)
    owners = [p.doc for p in r.pairs if "src/auth/session.py" in p.code_files]
    assert sorted(owners) == ["docs/auth.md", "docs/ops/runbook.md"]


def test_out_of_scope_pair_code_is_flagged():
    # scripts/deploy.sh is tracked but matches neither source nor docs scope:
    # the pair silently covers less than declared — must surface, not drop
    cfg = _cfg(pairs=[PairRule(doc="docs/auth.md", code=["src/auth/**", "scripts/**"])])
    files = FILES + ["scripts/deploy.sh"]
    r = resolve(cfg, files)
    assert r.out_of_scope_pair_code == ["docs/auth.md: scripts/**"]
    # the in-scope part of the pair still resolves normally
    pair = next(p for p in r.pairs if p.doc == "docs/auth.md")
    assert pair.code_files == ["src/auth/session.py", "src/auth/token.py"]


def test_pattern_matching_nothing_tracked_is_not_out_of_scope():
    # a glob that matches no tracked file at all is the orphan/dead territory,
    # not an out-of-scope finding (nothing was silently dropped)
    cfg = _cfg(pairs=[PairRule(doc="docs/auth.md", code=["future/**"])])
    r = resolve(cfg, FILES)
    assert r.out_of_scope_pair_code == []
    assert "docs/auth.md" in r.orphan_pairs


def test_doc_itself_on_code_side_is_not_out_of_scope():
    # self-reference is dropped as degenerate, not reported as out of scope
    cfg = _cfg(
        pairs=[PairRule(doc="docs/auth.md", code=["docs/auth.md", "src/auth/**"])]
    )
    r = resolve(cfg, FILES)
    assert r.out_of_scope_pair_code == []


def test_doc_matching_source_glob_is_not_uncovered_source():
    # README.md matches a broad source glob too — it classifies as a doc,
    # never as uncovered source (the doc-classification gate watches it)
    cfg = _cfg(
        source_include=["**"],
        pairs=[PairRule(doc="docs/auth.md", code=["src/**"])],
    )
    r = resolve(cfg, FILES)
    assert "README.md" not in r.uncovered_source
    assert "docs/orphan.md" not in r.uncovered_source
    assert "README.md" not in r.source_files
    # real code is still subject to the coverage floor
    assert all(f.endswith(".py") for f in r.source_files)
