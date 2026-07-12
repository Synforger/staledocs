# AI-agent integration

staledocs deliberately stops at detection. The judgement — "is the doc
stale, or is the code missing the spec?" — belongs to layer L3, which is
you or your coding agent. This page describes the loop.

## The loop

```
edit → staledocs check --json → agent triages each finding → agent fixes
     → staledocs ack <doc> (or a Staledocs-Ack trailer in the fix commit)
```

The agent never has to *trust* its own reading of the repo: the JSON report
is a deterministic ground truth of what moved and what rotted.

## Triage rules an agent can follow

| Finding | Meaning | Typical agent action |
|---|---|---|
| pair `DOC_STALE` | code moved, doc did not | read the diff of `changed_code` since `ack_commit`, update the doc, ack |
| pair `CODE_LAG` | doc moved, code did not | the doc is a spec change — implement it, or flag to the human |
| pair `BROKEN` | both moved separately | reconcile both sides, then ack |
| pair `AMBER` | both moved together | verify the prose still matches; ack to promote to green |
| pair `UNACKED` | no baseline yet | reconcile once, then ack |
| anchor finding | doc line quotes a dead identifier/path | fix the quote (rename? removal?) — the line number is exact |
| `uncovered_source` | new file has no owning doc | add it to a pair's glob, or write the doc the human asked for |
| `unclassified_docs` | new doc has no classification | pair it, or declare `standalone`/`global` |

Rule of thumb: an agent may *fix* and *ack* mechanical findings (anchors,
renames), but should surface judgement calls (`CODE_LAG` spec changes) to
the human rather than silently implementing them.

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
