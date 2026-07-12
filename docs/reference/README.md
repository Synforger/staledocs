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
| `pairs[].code` | globs | | code owned by that doc |
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

## Pair states

| State | Trigger | Gate class |
|---|---|---|
| `GREEN` | both sides match the last ack | — |
| `AMBER` | both moved, every code-touching commit also touched the doc | never blocks |
| `DOC_STALE` | code moved alone | red |
| `CODE_LAG` | doc moved alone (spec not implemented) | red |
| `BROKEN` | both moved in commits that did not travel together | red |
| `UNACKED` | no readable ledger entry | red |

Also red: anchor findings, `uncovered_source`, `unclassified_docs`,
`orphan_pairs` (pair globs match no code), `dead_pair_docs` (pair doc path
does not exist). `stale_ledger_docs` (ledger entry for an unmapped doc) is
reported but yellow — clean up with `staledocs ack --prune`.

## CLI

| Command | Purpose |
|---|---|
| `staledocs init` | scaffold config + ledger dir |
| `staledocs check [--json] [--all] [--gate warn\|strict]` | run all deterministic checks |
| `staledocs ack <doc...> [--all] [--broken] [--prune] [-m note]` | record coherence |
| `staledocs pairs [--json]` | show classification of every doc / source file |

## JSON contract (`check --json`)

```jsonc
{
  "staledocs": "0.1.1",
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
      "detail": ""
    }
  ],
  "anchors": [
    { "doc": "docs/auth.md", "line": 12, "token": "issue_token", "scope": "pair" }
  ],
  "coverage": {
    "unclassified_docs": [], "orphan_pairs": [], "uncovered_source": [],
    "dead_pair_docs": [], "stale_ledger_docs": []
  },
  "classification": { "paired": [], "standalone": [], "global": [] }
}
```

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
