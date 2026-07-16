# Setup

## Install

```sh
pip install staledocs        # Python 3.11+
staledocs --version
```

Works in any git repository — the tool reads git metadata, so a repo is the
one hard requirement.

## New repo (greenfield)

```sh
staledocs init
```

This writes a commented `.staledocs.yaml` (source roots are the top-level
dirs that hold tracked code — structural, not a name whitelist; docs are
every tracked `**/*.md`) and creates the `.staledocs/pairs/` ledger
directory. The guess is printed, never silent: init lists the roots it
detected, the top-level dirs it left out, and any frozen-docs subtrees
(`archive`/`legacy`/`history` paths) it suggests excluding — the tool
proposes, you declare. Declare your pairs, then:

```sh
staledocs check      # everything shows UNACKED / uncovered — expected
staledocs ack --all  # prints per-pair evidence + one token per pair, exits 3
staledocs ack <doc> --confirm <token> -m '<what you verified>'  # once per pair
# (init already recorded the config baseline; `ack --config` is only needed
#  after you edit the config — the diff against the scaffold is then shown)
```

Commit the config and the ledger (including `.staledocs/config-ack.json`).

## Existing repo (brownfield onboarding)

1. `staledocs init --suggest`, keep `gate: warn`. The suggestion resolves
   every doc's own anchors against the tree and prints a paste-ready
   `pairs:` proposal (plus standalone candidates for anchor-less docs) —
   onboarding becomes review-and-paste instead of write-from-scratch.
2. Review the proposal, then classify what remains: add `standalone`/
   `global` globs for docs with no code side, pair the rest. `staledocs
   pairs` shows what is still unclassified after each edit. Docs can pair
   to upstream docs too (requirements ↔ design chains) — list the upstream
   doc on the `code:` side.
3. When `pairs` is quiet, reconcile and run the two-step ack: `staledocs ack --all`
   batches every pair's evidence with its own token, then confirm each pair
   individually (`staledocs ack <doc> --confirm ...`), plus `staledocs ack --config`.
4. Flip to `gate: strict` and wire it into CI / pre-commit.
5. Optional: `staledocs pairs --health` shows which docs quote no anchors
   (those stay red on any code move) and which pairs are wide but thin —
   the two structural reasons a repo feels noisy.

The warn→strict split is deliberate: the completeness gate is only useful
once the pairing is complete, and blocking commits during onboarding just
gets the tool uninstalled.

## Triaging the first run

A brownfield first run on a real repo prints dozens of findings. That is
the tool being honest, not broken — but each finding needs a verdict, and
warn mode left to rot means nobody reads the report again. Sort every
finding into one of these buckets; each has exactly one correct move:

| what the finding is | how to tell | the move |
|---|---|---|
| real rot | the doc names a file/flag/identifier that genuinely no longer exists | fix the doc (or the code) — this is the tool's payload, don't ignore it away |
| not-an-identifier quote | git branch names, config-example snippets, tokens for another machine (`~/...`, other-repo paths) | `anchors.ignore` — one entry per token or a glob for a family, with a comment saying what it is |
| scope gap | coverage/mapping findings: unclassified doc, uncovered source, pair code outside scope | widen `include`, or declare `standalone`/`global` — never shrink the source scope to silence it |
| undeclared pair | a doc that clearly owns code but was never paired | add the pair, then two-step ack it |
| planned reference | a plan/roadmap doc quotes a path or identifier that does not exist *yet* | declare it: `` `planned:src/future.py` `` — pending markers report as their own never-red class every run, and once the path lands the marker is flagged for removal. Fenced code blocks / `anchors.ignore` remain alternatives for whole planned layouts |
| accurate history | the prose around the red *says* the path was removed ("old X retired", "superseded by Y") | leave the doc alone — it is correct. Read the surrounding text before editing any anchor red; "fixing" these deletes accurate history |

Rules of thumb while sorting:

- **Fix rot before adding ignores.** An ignore written to silence real rot
  is exactly the weakening the config baseline will flag later.
- **Comment every ignore entry.** Six months on, an uncommented token is
  indistinguishable from a silenced finding.
- **Re-run `staledocs check` after each bucket**, not at the end — the
  count dropping is how you notice a mis-sorted entry immediately.
- **Plan docs and specs are different animals.** A spec you *pair* is
  allowed to run ahead of the code — that is the CODE_LAG state, ack it as
  "spec ahead, acknowledged". A free-floating plan doc that nobody will
  keep in lockstep with the tree belongs outside the docs scope, with its
  future paths in fences.

## When to flip warn → strict

Flip when all three hold, and wire the gate into CI in the same change:

1. `staledocs check` reports 0 red on two consecutive working days (one
   clean run proves the moment, two prove the pairing survives real work).
2. `staledocs pairs` shows no unclassified docs and no uncovered source.
3. Every `anchors.ignore` entry carries a comment you would defend in
   review.

Strict from then on means red blocks CI — which is the point: from this
moment doc drift is a build failure, not a report.

## Recommended git hygiene

- Commit `.staledocs.yaml` and `.staledocs/pairs/` — the ledger is shared
  truth, not local state.
- Acks travel well in commit trailers (`Staledocs-Ack: docs/auth.md`) when
  you fix code and doc together and want the pair green in the same commit.
