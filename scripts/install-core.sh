#!/usr/bin/env bash
# =============================================================================
# personal-template / install:core (= back-port to existing repo)
# =============================================================================
# Copies `_core/` contents from this personal-template clone into a target
# repo that was NOT originally derived from the template. Useful for bringing
# older personal repos up to the current machinery (= anon-scan / docs-check /
# doctor / lint-versions / audit / clean / release driver / pre-commit hooks).
#
# Conflicts are preserved via `rsync --backup --suffix=.tmpl.orig` so the
# operator can diff + merge by hand. The target repo's existing files are
# never silently overwritten.
#
# Usage:
#   task install:core TARGET=/path/to/existing-repo
#   # or directly:
#   TARGET=/path/to/existing-repo bash _core/scripts/install-core.sh
#
# Env:
#   TARGET    Required. Absolute or relative path to the target repo's root.
#   DRY_RUN   Optional (=1). List planned copies without writing.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SOURCE_CORE="${SOURCE_ROOT}/_core"

# shellcheck source=../.tooling/local-ci/setup-lib.sh
source "${SOURCE_CORE}/.tooling/local-ci/setup-lib.sh"

TARGET="${TARGET:-}"
DRY_RUN="${DRY_RUN:-0}"

if [ -z "${TARGET}" ]; then
    log_fail "TARGET is required (= path to existing repo root)"
    echo "usage: TARGET=/path/to/existing-repo bash _core/scripts/install-core.sh" >&2
    exit 2
fi

TARGET="$(cd "${TARGET}" 2>/dev/null && pwd)" || {
    log_fail "TARGET not a directory: ${TARGET}"
    exit 2
}

if [ ! -d "${SOURCE_CORE}" ]; then
    log_fail "_core/ not found at ${SOURCE_CORE} (= run from a template-state personal-template clone)"
    exit 2
fi

if [ ! -d "${TARGET}/.git" ]; then
    log_fail "TARGET (${TARGET}) is not a git repo (= no .git/ dir found)"
    exit 2
fi

log_info "source: ${SOURCE_CORE}"
log_info "target: ${TARGET}"
log_info "dry_run: ${DRY_RUN}"

if ! command -v rsync >/dev/null 2>&1; then
    log_fail "rsync not installed (brew install rsync | apt install rsync)"
    exit 2
fi

# Files in _core/ that the target almost certainly already has; copying them
# would always trigger a backup. Skip unless explicitly requested.
EXCLUDES=(
    "--exclude=README.md"
    "--exclude=LICENSE"
    "--exclude=.gitignore"
    "--exclude=_README.md"
    "--exclude=docs/internals/template-usage.md"
    # template-management tooling: only meaningful inside personal-template
    # itself (deriving / back-porting), never inside a target repo
    "--exclude=personalize.py"
    "--exclude=setup-requirements.txt"
    "--exclude=scripts/init.py"
    "--exclude=scripts/install-core.sh"
    "--exclude=docs/internals/install-to-existing.md"
    # local build litter
    "--exclude=__pycache__/"
    "--exclude=*.pyc"
)

RSYNC_FLAGS=(-a --backup --suffix=.tmpl.orig "${EXCLUDES[@]}")
if [ "${DRY_RUN}" = "1" ]; then
    RSYNC_FLAGS+=(--dry-run --itemize-changes)
fi

echo
log_info "running rsync (= existing files will be backed up to <name>.tmpl.orig)"
rsync "${RSYNC_FLAGS[@]}" "${SOURCE_CORE}/" "${TARGET}/"

echo
if [ "${DRY_RUN}" = "1" ]; then
    log_info "DRY_RUN=1; nothing changed on disk"
else
    log_ok "install:core complete"
    log_info "review conflicts: find '${TARGET}' -name '*.tmpl.orig'"
    log_info "next: cd '${TARGET}' && git status   # ensure no unintended overwrite"
fi
