# Scout report rubric

The grader evaluates the scout's final assistant message against these
criteria. Each is scored independently; the overall result is
`satisfied` only when every criterion is met.

## Structure

- The report is under a markdown heading exactly named `## Drift report`.
- It contains three sub-sections in this order: `Summary`,
  `Detected drift`, `No-drift confirmations`.
- The `Summary` paragraph cites the analysis window (since-timestamp)
  + total event count reviewed + drift-signal count by severity.

## Detected-drift contract

Each bullet under `Detected drift` MUST include all three fields:

1. **Signal** — which of the canonical heuristics triggered
   (new-actor / heartbeat-drop / exit-skew / severity-spike /
   state-mirror-drift / other). Free-text-named anomalies outside the
   canonical set are `needs_revision` (the rubric explicitly rewards
   speaking the canon).
2. **Evidence** — exact tool call that produced the finding. Output
   showing the actual matching row(s) is mandatory. A bullet that
   says "events showed weird activity" without naming the query is
   `needs_revision`.
3. **Operator question** — a single yes/no question the operator can
   answer in ≤10 seconds. Vague calls ("review the dashboard") are
   `needs_revision`.

## Evidence discipline

- Every claim references either a Wing API call or a `bash-read-only`
  invocation. No tool-call reference → `needs_revision`.
- Status codes / row counts / actor_id strings quoted verbatim, not
  paraphrased.

## No-write check

- The report MUST NOT include text claiming any drift was auto-resolved
  or any HTTP method other than the final report POST.
- The report MUST NOT reference write endpoints other than
  `POST /api/v1/events` (the report write) + the runner-side
  `POST /api/v1/notifications`. If the report mentions calling any
  write API explicitly, the grader returns `failed` immediately.

## Empty-window case

If the analysis window has zero events OR no anchor signal triggers,
the report is exactly:

```
## Drift report

### Summary
No events / signals in window <since=ISO>. Operations look steady at
<ISO-of-run>.

### Detected drift
_None._

### No-drift confirmations
- New actor_id appearance: no new identity in window.
- Conductor heartbeat: last fire <ISO> (within 7-day window).
- Pulse job exit_code skew: no failing job clusters.
- Severity spike: notifications within trailing-7d baseline.
- State-mirror drift: migrations/upgrades sync with events.
```

Anything more elaborate on a quiet window is `needs_revision`.
