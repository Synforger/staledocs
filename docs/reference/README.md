# Reference

## Config: `.staledocs.yaml`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `version` | int | — (required) | config schema version, currently `1` |
| `gate` | `warn` \| `strict` | `warn` | `strict` exits non-zero when red findings exist |
| `source.include` | globs | — (required) | files subject to pairing and the coverage gate |
| `source.exclude` | globs | `[]` | carve-outs (vendored, generated) |
| `docs.include` | globs | `docs/**/*.md`, `README.md` | files treated as docs |
| `docs.exclude` | globs | `[]` | |
| `pairs[].doc` | path | | literal doc path (one entry per doc) |
| `pairs[].code` | globs | | what this doc tracks: source files **or other docs** — pairing a doc to an upstream doc declares a chained-drift link (requirements ↔ design ↔ code), same ledger, same anchor grading; a doc never pairs to itself |
| `mirror.enabled` | bool | `false` | convention pairing `docs/<x>.md` ↔ `<code_root>/<x>/**` and `<code_root>/<x>.*` |
| `mirror.docs_root` | path | `docs` | |
| `mirror.code_roots` | paths | `[src]` | |
| `standalone` | globs | `[]` | docs with intentionally no code side |
| `global` | globs | `[]` | whole-repo docs: anchors only, no ledger |
| `anchors.min_length` | int | `3` | shortest token considered an anchor |
| `anchors.ignore` | strings | `[]` | exact tokens to skip |
| `anchors.include_fenced` | bool | `false` | also extract anchors inside fenced code blocks |
| `anchors.path_roots` | paths | `[]` | extra prefixes tried when resolving doc-quoted paths (docs describing a deployed subtree, e.g. `[src]`) |

Glob semantics are CODEOWNERS-flavoured: `*` stays within a path segment,
`**` crosses segments, a literal directory path matches everything under it.

Anchor resolution notes: paths that .gitignore rules would ignore pass (docs
legitimately describe runtime artifacts); markdown-relative references
(`../<dir>/<page>.md`) resolve against the doc's own directory;
`path::symbol` anchors resolve the file and grep the symbol inside it (a
gitignored path passes whole); call/assignment/subscript/glob notation falls
back to the bare identifier (`truncate()`, `viewMode='x'`, `loading[sid]`,
`system_*`); a slashless glob (`detect-*`) also matches tracked-file
basenames; tokens starting with `~`, `/`, or `$`, tokens containing `://`,
tokens whose digits outnumber their letters, and `<placeholder>` notation
are not extracted at all.

## Pair states

| State | Trigger | Gate class |
|---|---|---|
| `GREEN` | both sides match the last ack | — |
| `AMBER` | both moved together (co-movement), **or** code moved but nothing the doc names was touched (anchor-graded) | never blocks |
| `DOC_STALE` | code moved alone **and** the change touches something the doc names — a path-anchored file, or an added/removed line containing a quoted identifier | red |
| `CODE_LAG` | doc moved alone (spec not implemented) | red |
| `BROKEN` | both moved in commits that did not travel together | red |
| `UNACKED` | no readable ledger entry | red |

Anchor grading (v0.2): a path anchor hits at file granularity (the doc talks
about the file as a unit); an identifier anchor hits at line granularity
(the token appears in the added/removed lines since the ack). A doc with no
anchors at all gives the grader nothing and stays red on any code move —
quote paths and identifiers to earn the amber downgrade.

Also red: anchor findings, `uncovered_source`, `unclassified_docs`,
`orphan_pairs` (pair globs match no code), `dead_pair_docs` (pair doc path
does not exist), config weakenings (see below). `stale_ledger_docs` (ledger
entry for an unmapped doc) is reported but yellow — clean up with
`staledocs ack --prune`.

## Config weakening detection

Weakening the checks is itself a checked event. `check` compares the current
`.staledocs.yaml` against the last accepted baseline
(`.staledocs/config-ack.json`) and reds every weakening direction: gate
`strict` → `warn`, a pair removed, `source.include` dropped or
`source.exclude` added (scope narrowed), same for docs scope,
`anchors.min_length` raised, `anchors.ignore` grown, `include_fenced`
switched off. Strengthening directions never fire.

Accept a deliberate weakening with `staledocs ack --config -m '<why>'` —
the note is recorded in the baseline file. A missing baseline is a yellow
hint, not red (v0.1 repos upgrade without breaking); any successful pair
ack auto-advances the baseline when nothing weakened.

## CLI

| Command | Purpose |
|---|---|
| `staledocs init [--suggest]` | scaffold config + ledger dir; `--suggest` prints a paste-ready pairs proposal derived from each doc's own anchors (works standalone on an existing config, never writes) |
| `staledocs check [--json] [--all] [--gate warn\|strict]` | run all deterministic checks |
| `staledocs ack <doc...> [--all] [--broken] [--prune] [--confirm TOKEN] [--config] [-m note]` | record coherence (two-step for broken pairs) |
| `staledocs explain [doc...] [--json]` | evidence view for broken pairs — never gates |
| `staledocs pairs [--json] [--health]` | classification; `--health` = anchor density + ack age diagnostics |

### The two-step ack

A broken pair does not ack in one shot:

1. `staledocs ack <doc>` prints the evidence — the doc's own lines next to
   the changed lines they name — plus an evidence token, and exits `3`
   without writing anything.
2. `staledocs ack <doc> --confirm <token> -m '<note>'` records the ack. The
   token must match the current pair content (if either side moved since
   step 1, the confirm is refused), and the note must name something from
   the evidence: a changed file, a quoted anchor, or the doc itself.

Green pairs re-ack directly (nothing to verify). Bulk paths (`--all`,
`--broken`) use the same two steps with one aggregate token; their note must
be non-empty but is not content-checked (an onboarding baseline has no
single evidence to name). The `Staledocs-Ack:` commit trailer is untouched —
that path stays the human shortcut for fix-code-and-doc-together commits.

Trailer resolution walks the history after the acked commit; when that
commit is unknown to the clone (a squash merge discarded the branch tip it
was recorded on), the scan falls back to the full history rather than going
blind. A shallow clone has no history to scan — fetch full history in CI.

Exit codes: `0` ok, `1` gate failure / error, `2` usage error, `3` pending
confirmation.

## JSON contract (`check --json`)

```jsonc
{
  "staledocs": "1.1.0",
  "schema": 1,
  "gate": "warn",
  "summary": { "red": 2, "amber": 1, "green": 7 },
  "pairs": [
    {
      "doc": "docs/auth.md",
      "state": "DOC_STALE",          // see table above
      "origin": "explicit",          // or "mirror"
      "code_files": ["src/auth/token.py"],
      "changed_code": ["src/auth/token.py"],
      "doc_changed": false,
      "added_code": [], "removed_code": [],
      "rename_hints": { "old.py": "new.py" },
      "ack_commit": "abc123…", "ack_at": "2026-07-13T00:00:00+00:00",
      "detail": "",
      "mentioned_changed": ["src/auth/token.py"],   // changed files the doc names
      "hit_anchors": [                              // the intersection evidence
        {
          "file": "src/auth/token.py",
          "token": "issue_token",
          "kind": "ident",                          // or "path"
          "doc_lines": [12],
          "changed_lines": ["def issue_token(ttl=60):"]
        }
      ]
    }
  ],
  "anchors": [
    { "doc": "docs/auth.md", "line": 12, "token": "issue_token", "scope": "pair" }
  ],
  "coverage": {
    "unclassified_docs": [], "orphan_pairs": [], "uncovered_source": [],
    "dead_pair_docs": [], "stale_ledger_docs": []
  },
  "config": { "weakenings": [], "baseline_missing": false },
  "classification": { "paired": [], "standalone": [], "global": [] }
}
```

`staledocs explain --json` returns the same evidence per broken pair plus a
`token` field — the evidence token the two-step ack expects, so an agent can
go straight from reading the evidence to confirming.

Compatibility promise: within a major version, keys are only added — never
renamed or removed.

## Ledger format

One JSON file per pair under `.staledocs/pairs/`, named
`<slug>-<sha1-8>.json`:

```json
{
  "schema": 1,
  "doc": "docs/auth.md",
  "ack": {
    "commit": "abc123…",
    "doc_blob": "…",
    "code_blobs": { "src/auth/token.py": "…" },
    "at": "2026-07-13T00:00:00+00:00",
    "note": ""
  }
}
```

Any entry that fails to parse (merge conflict markers included) is treated
as absent — the pair reverts to `UNACKED`. A merge can never manufacture a
green state.

The accepted config baseline lives next to the pairs as
`.staledocs/config-ack.json` (`schema`, `accepted` snapshot, `note`, `at`)
and follows the same fail-safe rule: unreadable = missing.
