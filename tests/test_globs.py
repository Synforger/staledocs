from staledocs import globs


def test_star_stays_in_segment():
    assert globs.matches("src/*.py", "src/a.py")
    assert not globs.matches("src/*.py", "src/deep/a.py")


def test_double_star_crosses_segments():
    assert globs.matches("src/**", "src/a.py")
    assert globs.matches("src/**", "src/deep/nested/a.py")
    assert not globs.matches("src/**", "src")
    assert not globs.matches("src/**", "other/a.py")


def test_double_star_prefix():
    assert globs.matches("**/conftest.py", "conftest.py")
    assert globs.matches("**/conftest.py", "tests/deep/conftest.py")


def test_literal_matches_exact_and_dir_prefix():
    assert globs.matches("src/auth", "src/auth/token.py")
    assert globs.matches("docs/auth.md", "docs/auth.md")
    assert not globs.matches("docs/auth.md", "docs/auth.md.bak")


def test_question_mark():
    assert globs.matches("src/v?.py", "src/v1.py")
    assert not globs.matches("src/v?.py", "src/v12.py")


def test_filter_paths_include_exclude():
    paths = ["src/a.py", "src/vendor/b.py", "docs/x.md"]
    got = globs.filter_paths(paths, ["src/**"], ["src/vendor/**"])
    assert got == ["src/a.py"]
