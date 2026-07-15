# AI-agent integration

staledocs deliberately stops at detection. The judgement — "is the doc
stale, or is the code missing the spec?" — belongs to layer L3, which is
you or your coding agent. This page describes the loop.

## The loop

```
edit → staledocs check --json → staledocs explain --json (evidence per break)
     → agent triages, fixes → staledocs ack <doc> (exit 3: evidence + token)
     → agent reads the evidence → staledocs ack <doc> --confirm <token> -m '<note>'
       (or a Staledocs-Ack trailer in the fix commit)
```

The agent never has to *trust* its own reading of the repo: the JSON report
is a deterministic ground truth of what moved and what rotted. The two-step
ack exists precisely because agents can stamp without looking — step 1
prints the doc's own lines next to the changed lines they name, and the
confirm token cannot be produced without parsing that output. The note must
name something from the evidence; "looks fine" is refused.

`explain --json` carries the same evidence blocks plus the `token`, so a
repair loop can read once and confirm directly. Exit codes: `0` ok, `1`
gate/error, `2` usage, `3` pending confirmation.

## Triage rules an agent can follow

| Finding | Meaning | Typical agent action |
|---|---|---|
| pair `DOC_STALE` | the change touched something the doc names (`hit_anchors` says which line quotes what) | compare each hit's `doc_lines` with `changed_lines`, update the doc, two-step ack |
| pair `CODE_LAG` | doc moved, code did not | the doc is a spec change — implement it, or flag to the human |
| pair `BROKEN` | both moved separately | reconcile both sides, then ack |
| pair `AMBER` | both moved together, or nothing the doc names was touched | verify the prose still matches; ack to promote to green (optional — amber never blocks) |
| pair `UNACKED` | no baseline yet | reconcile once, then ack |
| anchor finding | doc line quotes a dead identifier/path | fix the quote (rename? removal?) — the line number is exact |
| `uncovered_source` | new file has no owning doc | add it to a pair's glob, or write the doc the human asked for |
| `unclassified_docs` | new doc has no classification | pair it, or declare `standalone`/`global` |
| config weakening | a check got weaker vs the accepted baseline | never self-accept: surface to the human; acceptance is `ack --config` with a reason |

Rule of thumb: an agent may *fix* and *ack* mechanical findings (anchors,
renames), but should surface judgement calls (`CODE_LAG` spec changes,
config weakenings) to the human rather than silently accepting them. Bulk
stamps (`ack --all` / `--broken`) are onboarding tools — an agent working a
normal change should ack the specific docs it verified, nothing wider.

## Hook example (Claude Code)

Run a check after every file edit and feed findings back to the agent:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "staledocs check --gate warn 2>/dev/null | tail -5"
          }
        ]
      }
    ]
  }
}
```

Keep the hook on `--gate warn` (report, never block an edit mid-flight);
put `--gate strict` in CI or pre-commit where blocking is the point.

## JSON contract

See [Reference](reference/) for the full schema. Compatibility promise:
keys are only added, never renamed or removed, within a major version.
