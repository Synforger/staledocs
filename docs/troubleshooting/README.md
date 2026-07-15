# Troubleshooting

One problem per section: symptom → cause → fix.

## Too many anchor findings on day one

**Symptom**: `check` reports dozens of `[anchor]` lines on a freshly paired
doc. **Cause**: the doc quotes generic words in backticks (`config`, `data`)
or references identifiers that never existed verbatim. **Fix**: raise
`anchors.min_length`, add exact tokens to `anchors.ignore`, or rewrite the
doc to quote real identifiers — the findings are pointing at prose that a
reader cannot grep either.

## A pair is AMBER and never turns green

**Symptom**: `AMBER` persists across commits. **Cause**: amber never
promotes itself — it means "moved together, unconfirmed" and waits for a
judgement. **Fix**: read the pair once, then `staledocs ack <doc>` or put a
`Staledocs-Ack:` trailer in the next commit touching the pair.

## Everything went red after a big refactor

**Symptom**: dozens of `DOC_STALE`/`BROKEN` pairs after a sweeping rename.
**Cause**: expected — the code genuinely moved away from every ack.
**Fix**: reconcile the docs that matter, then `staledocs ack --broken`
to re-baseline in one command. Check `rename_hints` in `check --json`
first: pure renames can be acked without doc edits.

## Ledger file merge conflict

**Symptom**: git reports a conflict in `.staledocs/pairs/<pair>.json`.
**Cause**: both branches acked the same pair. **Fix**: keep either side or
neither — a file with conflict markers simply stops parsing and the pair
reverts to `UNACKED` (fail-safe). Re-run `staledocs ack <doc>` after the
merge and the entry is rewritten cleanly.

## Monorepo: docs for one package keep flagging another package's files

**Symptom**: `uncovered_source` lists files you consider out of scope.
**Cause**: `source.include` is broader than the docs you actually maintain.
**Fix**: narrow `source.include` to the trees you are willing to pair, or
add explicit `source.exclude` globs. The coverage gate is only meaningful
over the set you commit to.

## `check` is slow on a huge repo

**Cause**: anchor verification reads every paired file once per doc.
**Fix**: keep pairs narrow (a doc owning `src/**` re-reads the world),
prefer per-package pairs, and exclude vendored trees from `source.include`.

## gitleaks flags the pair ledger as an API key

**Symptom**: a pre-commit secret scanner (gitleaks `generic-api-key`) blocks
a commit touching `.staledocs/pairs/*.json`. **Cause**: the ledger stores
git blob hashes — 40-hex strings that trip entropy heuristics. **Fix**: add
a path allowlist to your repo's gitleaks config:

```toml
[allowlist]
description = "staledocs pair ledger stores git blob hashes, not secrets"
paths = ['''\.staledocs/pairs/.*\.json$''']
```

## `ack` exits 3 and nothing was recorded

**Symptom**: `staledocs ack docs/x.md` prints an evidence block plus a
`--confirm <token>` line and exits `3`; the ledger did not change.
**Cause**: not an error — this is step 1 of the two-step ack for broken
pairs. **Fix**: read the evidence, then rerun with
`--confirm <token> -m '<note>'`. Exit `3` specifically means "pending
confirmation" so hooks can tell it apart from a real failure (`1`) or a
usage error (`2`).

## Confirm refused: "note must name something from the evidence"

**Symptom**: step 2 of an ack fails even with a token. **Cause**: the note
is a rubber stamp — it names nothing the evidence showed. **Fix**: mention
a changed file, a quoted anchor, or the doc itself
(`-m 'issue_token return shape unchanged, doc still accurate'`). The check
is deterministic substring matching, not semantic judgement.

## Confirm refused: "evidence token mismatch"

**Symptom**: `--confirm` fails with a token you just received. **Cause**:
either side of the pair moved between step 1 and step 2 — the evidence you
read is no longer the state you are stamping. **Fix**: rerun `staledocs
ack` and read the fresh evidence; the new token supersedes the old one.
