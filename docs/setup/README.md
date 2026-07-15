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

This writes a commented `.staledocs.yaml` (source/docs globs guessed from
your tree) and creates the `.staledocs/pairs/` ledger directory. Declare
your pairs, then:

```sh
staledocs check      # everything shows UNACKED / uncovered — expected
staledocs ack --all  # prints per-pair evidence + one token per pair, exits 3
staledocs ack <doc> --confirm <token> -m '<what you verified>'  # once per pair
staledocs ack --config -m 'initial baseline'   # record the config baseline too
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

## Recommended git hygiene

- Commit `.staledocs.yaml` and `.staledocs/pairs/` — the ledger is shared
  truth, not local state.
- Acks travel well in commit trailers (`Staledocs-Ack: docs/auth.md`) when
  you fix code and doc together and want the pair green in the same commit.
