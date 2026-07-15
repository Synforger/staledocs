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
staledocs ack --all  # prints per-pair evidence + a token, exits 3
staledocs ack --all --confirm <token> -m 'onboarding baseline'
staledocs ack --config -m 'initial baseline'   # record the config baseline too
```

Commit the config and the ledger (including `.staledocs/config-ack.json`).

## Existing repo (brownfield onboarding)

1. `staledocs init`, keep `gate: warn`.
2. Classify in passes, largest first: add `standalone`/`global` globs for
   docs with no code side, then pair the rest. `staledocs pairs` shows what
   is still unclassified after each edit.
3. When `pairs` is quiet, reconcile and run the two-step `staledocs ack --all`
   (evidence + token, then `--confirm`), plus `staledocs ack --config`.
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
