# Remediator report rubric

The grader evaluates the remediator's final assistant message against
these criteria. Each is scored independently; the overall result is
`satisfied` only when every criterion is met.

## Structure

- The report is under a markdown heading exactly named `## Remediation report`.
- It contains three sub-sections in this order: `Summary`, `Per-finding analysis`, `Recommendations`.
- The `Summary` paragraph cites the total finding count + severity histogram.

## Per-finding contract

For each finding analyzed, the section MUST include all five required
fields, IN ORDER:

1. **Fingerprint** — gitleaks fingerprint verbatim.
2. **Severity** — verbatim from the row (critical/high/medium/low/info).
3. **Evidence** — a fenced code block showing 4 lines of context above
   and 4 below `line_start`. Missing context (e.g. file moved) is
   acceptable IFF the report says so explicitly and references the
   `bash-read-only` call that returned the empty/error result.
4. **Proposed fix** — exactly one concrete remediation. Vague
   suggestions (e.g. "rotate the key" with no indication of how) are
   `needs_revision`.
5. **Operator action** — a verb-noun pair the operator can act on
   without further interpretation. Acceptable examples:
   `Mark resolved (false positive)`, `Rotate AWS key + replace literal`,
   `Quarantine commit + force-push history rewrite`.

## Evidence discipline

- Every claim in the report references either a Wing API call or a
  `bash-read-only` invocation. A bullet without a tool-call reference
  is `needs_revision`.
- Status codes, file paths, and line numbers are quoted verbatim, not
  paraphrased.

## No-auto-resolve check

- The report MUST NOT include text claiming any finding was auto-
  resolved, auto-fixed, or auto-committed. If such text appears the
  grader returns `failed` immediately (no `needs_revision` retry).
- The report MUST NOT reference any HTTP method other than GET against
  Wing or Bone (except the final `POST /api/v1/notifications` the
  runner makes — that's outside the model's tool surface).

## Empty-findings case

If the open findings list is empty, the report is exactly:

```
## Remediation report

### Summary
No open findings as of <ISO-8601 UTC>. Run took <N>ms.

### Per-finding analysis
_None._

### Recommendations
- Continue routine scans; next gitleaks Pulse run scheduled for <next-fire-at>.
```

Anything more elaborate on an empty findings list is `needs_revision`
(the rubric explicitly rewards conciseness in the green-path case).
