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
