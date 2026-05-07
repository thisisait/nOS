# Conductor report rubric

The grader evaluates the conductor's final assistant message against these
criteria. Each is scored independently; the overall result is `satisfied`
only when every criterion is met.

## Structure

- The report is under a markdown heading exactly named `## Conductor report`.
- It contains three sub-sections in this order: `Health`, `Findings`,
  `Recommendations for operator`.
- The `Health` line uses one of: `ok`, `degraded`, `failed`. Anything else
  is `needs_revision`.

## Evidence discipline

- Every `Findings` bullet references the tool call that produced the
  evidence (e.g. `mcp_wing GET /api/v1/hub/health → 200`). A bullet without
  a tool-call reference is `needs_revision`.
- Status codes / error messages are quoted verbatim, not paraphrased.
- The agent did not draw conclusions beyond what the tool calls returned
  (no hallucinated services, no invented timestamps).

## Self-test coverage

The agent ran at least these checks (per system.md):

- `mcp_wing GET /api/v1/hub/health`
- `mcp_wing GET /api/v1/pulse_jobs`
- `mcp_wing GET /api/v1/events?limit=5`
- one `bash_read_only` git status check
- one `bash_read_only` sqlite3 events-last-24h query

If any of these is missing AND the report claims `Health: ok`, the result is
`needs_revision`. If a check failed and the report explicitly explains why
the tool call returned the failure, the result is `satisfied` (the
conductor's job is to report, not to fix).

## Recommendations

- Empty `Recommendations` list when `Health: ok` is correct + expected.
- Non-empty list when `Health: degraded|failed` — at least one bullet must
  identify the human action needed.
- Bullets are imperative ("Restart Authentik server", "Check `wing.db` size
  growth") — descriptive paragraphs are `needs_revision`.

## Failure mode

`failed` (not `needs_revision`) is reserved for: the rubric does not match
the task at all (e.g. the operator gave a custom prompt that has nothing to
do with health-checking). Do not return `failed` for a salvageable report —
ask for revision instead.
