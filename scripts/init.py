#!/usr/bin/env python3
"""Initialise a repo derived from personal-template.

Promotes `_core/` to the repo root, resets the project version, and removes
template-only scaffolding. The template ships no language scaffolding — after
init, fill in the stack stubs in Taskfile.yml (or add a Taskfile.local.yml)
with your project's real commands.

Usage:
    task init
    # or directly:
    python3 _core/scripts/init.py
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CORE = REPO_ROOT / "_core"


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def confirm_layout() -> None:
    if not CORE.is_dir():
        fail(f"_core/ not found at {CORE} (= already initialised?)")
    if REPO_ROOT / ".git" not in [p for p in REPO_ROOT.iterdir()]:
        # Not fatal — a worktree or submodule layout keeps .git elsewhere.
        pass


# Files in _core/ that are expected to overwrite their template-state
# counterparts at the repo root. README.md + Taskfile.yml at the root are
# template-only scaffolding (= "use this template" intro + `task init` only)
# and must be replaced with the derived-repo versions from _core/.
ALLOW_ROOT_OVERWRITE = {"README.md", "Taskfile.yml"}


def promote_core() -> None:
    for path in sorted(CORE.iterdir()):
        if path.name == "_README.md":
            # Template-internal doc explaining what `_core/` is. Not part of
            # the derived repo.
            path.unlink()
            continue
        dst = REPO_ROOT / path.name
        if dst.exists():
            if path.name in ALLOW_ROOT_OVERWRITE and dst.is_file():
                dst.unlink()
            else:
                fail(f"refusing to overwrite existing {dst.name} at repo root")
        shutil.move(str(path), str(dst))
    CORE.rmdir()
    print(f"  promoted _core/ → repo root ({sum(1 for _ in REPO_ROOT.iterdir())} entries)")


def reset_project_version() -> None:
    """Reset current_version in bump-targets.yaml to 0.0.0 for the new project."""
    bt = REPO_ROOT / ".tooling" / "bump-targets.yaml"
    if not bt.exists():
        return
    text = bt.read_text()
    text = re.sub(
        r"^current_version:.*$",
        "current_version: 0.0.0",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    bt.write_text(text)
    print("  reset current_version to 0.0.0")


def cleanup_template_only_files() -> None:
    # docs/internals/template-usage.md is template-state guidance, not for
    # the derived repo.
    p = REPO_ROOT / "docs" / "internals" / "template-usage.md"
    if p.exists():
        p.unlink()
        print(f"  removed template-only doc {p.relative_to(REPO_ROOT)}")


def main() -> int:
    confirm_layout()

    print("==> Promoting _core/ contents to repo root")
    promote_core()

    print("==> Resetting project version")
    reset_project_version()

    print("==> Removing template-only files")
    cleanup_template_only_files()

    print()
    print("==> Template promoted. Next steps:")
    print("    1. pip install -r setup-requirements.txt && python3 personalize.py")
    print("    2. Fill in the stack stubs in Taskfile.yml (setup / lint / test / build / run)")
    print("       — or keep them in a separate Taskfile.local.yml")
    print("    3. Add your version files to .tooling/bump-targets.yaml targets")
    print("    4. task doctor        (= toolchain preflight)")
    print("    5. task init:github   (= optional: apply post-template GitHub settings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
