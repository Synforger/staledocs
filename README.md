# staledocs

Deterministic drift detection between code and docs. Language-agnostic,
no LLM in the detection path.

Documentation language: English ([`README.ja.md`](README.ja.md) carries the
Japanese version).

## The problem

Docs rot silently. You change the code, the doc keeps describing the old
behaviour, and nobody notices until the doc misleads a teammate — or an AI
agent, which then confidently implements against a stale spec. The fear of
that rot is also why people stop writing docs at all: every page is a
maintenance debt you have to *remember*.

staledocs removes the remembering. It pairs every doc with the code it
describes, records a fingerprint when you confirm they match, and from then
on any one-sided change is flagged mechanically — in either direction.

## How it works

Four detection layers; the first three are deterministic, no AI anywhere:

1. **Pair ledger, anchor-graded (L1)** — each doc/code pair stores the git
   blob hashes from the last time a human (or agent) confirmed coherence
   (an *ack*). Code moved but the doc did not → red **only when the change
   touches something the doc names**: a file it path-anchors, or an
   added/removed line containing an identifier it quotes. Unrelated churn
   inside a wide pair downgrades to `AMBER` with the reason spelled out —
   red keeps its urgency. Doc moved but the code did not → `CODE_LAG`
   (unimplemented spec). Both moved in commits that travelled together →
   `AMBER`. Both moved separately → `BROKEN`.
2. **Anchor liveness (L2)** — docs naturally quote identifiers, CLI flags,
   and paths in backticks. staledocs extracts those anchors and verifies
   each one still exists on the paired code side, reporting the exact doc
   line that rotted. The doc is parsed; the code is only grepped — that is
   what keeps the tool language-agnostic.
3. **Coverage gates** — every source file must belong to at least one doc,
   and every doc must be classified (paired, standalone, or global).
   New files with no owner show up red immediately. Silence is never
   coverage.
4. **Semantic reconciliation (L3, external by design)** — judging whether
   prose still matches behaviour is not a deterministic problem. staledocs
   emits a machine-readable report (`check --json`) and leaves the fixing to
   you or your AI agent, which then closes the loop with an ack.

## Quick start

```sh
pip install staledocs

cd your-repo
staledocs init            # scaffold .staledocs.yaml + ledger dir
$EDITOR .staledocs.yaml   # declare the pairing (see below)
staledocs check           # see what's unowned / unacked
staledocs ack --all       # baseline step 1: evidence + token (exit 3)
staledocs ack --all --confirm <token> -m 'onboarding baseline'
```

From then on:

```sh
staledocs check             # after any change: what broke?
staledocs explain           # the doc's words next to the change that hit them
staledocs ack docs/auth.md  # step 1: evidence + token
staledocs ack docs/auth.md --confirm <token> -m 'issue_token still per doc'
```

## Pairing model

CODEOWNERS-style globs, one YAML file:

```yaml
version: 1
gate: warn                 # warn (report) | strict (non-zero exit on red)

source:
  include: ["src/**"]
docs:
  include: ["docs/**/*.md", "README.md"]

pairs:
  - doc: docs/auth.md
    code: ["src/auth/**"]           # a folder
  - doc: docs/token.md
    code: ["src/auth/token_*.py"]   # or a slice of one

mirror:                    # optional convention: docs/<x>.md <-> src/<x>/**
  enabled: true
  docs_root: docs
  code_roots: [src]

standalone:                # docs that intentionally have no code side
  - "docs/ops/**"
global:                    # whole-repo docs: anchors only, no pair ledger
  - README.md
```

Explicit pairs win over the mirror convention. N:M is natural — one file may
be owned by several docs, one doc may own several globs.

## Acks

An ack is the recorded statement "this pair is coherent right now". Three
ways to give one:

- `staledocs ack docs/auth.md` — explicit, after you reconciled. A broken
  pair acks in two steps: the first run prints the evidence (the doc's own
  lines next to the changed lines they name) plus a token; the second run
  passes `--confirm <token>` with a note that names something from that
  evidence. A stamp given without reading is structurally impossible — the
  token only exists in the evidence output, and "looks fine" notes are
  refused.
- `staledocs ack --broken` / `--all` — bulk (refactor days, onboarding),
  same two steps with one aggregate token
- a `Staledocs-Ack: docs/auth.md` (or `Staledocs-Ack: all`) commit-message
  trailer — ack in the same breath as the change (the human shortcut,
  no token needed)

Editing code and doc in the same commit is treated as `AMBER` automatically:
honest "probably coherent, unconfirmed", never a silent green.

Weakening the checks is itself checked: dropping a pair, downgrading the
gate, or growing the ignore list turns `check` red until someone records
`staledocs ack --config -m '<why>'`. The backdoor has a doorbell.

The ledger lives in `.staledocs/pairs/` as one JSON file per pair and is
meant to be committed. A merge conflict in a ledger entry fails safe: the
entry stops parsing, the pair reverts to unacked, and gets re-checked.

## CI and hooks

```yaml
# GitHub Actions
- run: pip install staledocs
- run: staledocs check --gate strict
```

```sh
# pre-commit hook
staledocs check --gate strict || exit 1
```

Start with `gate: warn` while onboarding a brownfield repo, flip to
`strict` once `check` is quiet.

## AI-agent integration

`staledocs check --json` is the agent API: every broken pair with its moved
files and `hit_anchors` evidence, every dead anchor with its doc line, every
coverage hole. `staledocs explain --json` adds the evidence token, so a
repair loop reads once and confirms directly. A coding agent consumes the
report, decides per finding whether the doc or the code is wrong, fixes that
side, and closes with the two-step ack — which it cannot pass without
parsing the evidence. staledocs supplies the trustworthy signal; the agent
supplies the judgement. See
[`docs/agent-integration.md`](docs/agent-integration.md).

## Design principles (also the non-goals)

- **Detection is deterministic.** Git blob hashes, commit topology, and
  anchor grepping. If staledocs says a pair broke, it broke.
- **No doc generation.** The tool never adds to your documentation burden;
  it guards what you chose to write.
- **No code parsing.** No per-language AST, no parser tiers, no silent
  degradation on language N+1. Works the same for Python, TypeScript, Rust,
  shell, or anything else.
- **No LLM in the detection path.** Semantic judgement is the ack's job —
  yours, or your agent's.

Prior art: the coherence-driven idea owes a nod to
[CoDD](https://github.com/yohey-w/codd-dev), which attacks the same problem
from the generative side. staledocs deliberately takes the opposite bet:
detect deterministically, generate nothing.

## License

Apache-2.0 ([`LICENSE`](LICENSE)). Dependency notices in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md); vulnerability reporting
in [`SECURITY.md`](SECURITY.md).
