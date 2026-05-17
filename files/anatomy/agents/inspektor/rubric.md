# Inspektor report rubric

> Contract-only (2026-05-17). The grader rubric below applies once the
> runner lands and inspektor produces actual scan output.

## Structure

- Report under heading `## Pentest survey report`.
- Three sub-sections, in order: `Scan summary`, `New findings`,
  `Recommendations`.
- `Scan summary` cites the scan substrate invoked (gitleaks / trivy /
  nuclei / etc.) + the scan_id + total findings count by severity.

## New-findings contract

Each bullet under `New findings` MUST include:

1. **Substrate** — which scan produced it.
2. **Severity** — critical / high / medium / low / info (rubric
   explicitly penalizes severity inflation; bullets that grade higher
   than the substrate's own classification need explicit operator-
   visible justification).
3. **Fingerprint** — substrate-native key (gitleaks fingerprint, CVE
   ID, nuclei template ID, etc.).
4. **Evidence** — the tool call output proving the finding exists.
5. **Triage hint** — "operator action" verb-noun, same shape as
   remediator's output. Future runs by remediator + analyst eyes
   read this column.

## No-auto-remediation check

- The report MUST NOT include text claiming any finding was
  auto-resolved or auto-patched. Inspektor's scope is `write`, not
  `resolve`. If such text appears the grader returns `failed`
  immediately.
- The report MUST NOT reference any HTTP method other than the
  finding POSTs + the final report write.

## Empty-scan case

If the scan produces zero findings, the report is exactly:

```
## Pentest survey report

### Scan summary
<substrate> scan at <ISO> against <target>: 0 findings.

### New findings
_None._

### Recommendations
- Continue routine scheduled scans; next <substrate> run scheduled for <next-fire-at>.
```

## Severity-calibration check

Concrete penalty: if inspektor surfaces a critical finding without
showing the substrate's own severity classification verbatim, the
grader downgrades to `needs_revision`. Goal: every operator-visible
severity must be backed by the substrate's classification, not the
agent's judgment.
