# Third-Party Notices

This file enumerates every OSS dependency `{{repo_full_name}}` ships
against (= direct + transitive) along with each license. It is
**auto-generated** by `task gen-notices` (= wraps `pip-licenses`
for Python and `license-checker-rseidelsohn` for Node). Do not edit
this file by hand; re-run `task gen-notices` and commit the diff.

## Why it ships in the repo

GitHub Actions + npm registries + PyPI all change license metadata
asynchronously, so a snapshot in-tree is the only stable artefact for
downstream review. Anyone reading the repo can confirm what they will
be installing without first running `task setup`.

## Regeneration

```
task gen-notices
git diff --stat THIRD_PARTY_NOTICES.md
git add THIRD_PARTY_NOTICES.md
git commit -m "chore: refresh THIRD_PARTY_NOTICES"
```

Trigger conditions:
- After every `pip install` / `npm install` / `cargo add` that touches
  a new direct dep
- Quarterly even when no new deps were added (= transitive deps shift)
- Before every tagged release (= snapshot for the release notes)

## Initial state

This file is a placeholder until `task gen-notices` runs once. After
the first run the table below is replaced with the real dependency
list:

| package | version | license | source |
|---|---|---|---|
| (run `task gen-notices` to populate) | — | — | — |
