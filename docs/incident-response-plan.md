# Incident Response & Breach-Notification Plan

> Operator + DPO runbook for the nOS breach-notification engine (gov-readiness
> P0 #4). Closes the audit gap "no operational breach-notification capability".
> Companion controls: [`security-baseline.md`](security-baseline.md) (DPO
> one-pager, controls inventory) and [`restore-runbook.md`](restore-runbook.md)
> (business-continuity / disaster recovery).

A single event can owe duties on **two parallel tracks** — record it once; the
engine computes both:

| Track | Authority | Clock anchor | Deadlines |
|---|---|---|---|
| **GDPR personal-data breach** | Supervisory authority — **ÚOOÚ** (Art 33); data subjects (Art 34) | `aware_at` ("became aware") | Art 33: **72h** to ÚOOÚ (only if risk); Art 34: data subjects "without undue delay" (only if **high** risk) |
| **NIS2 / ZKB cyber incident** | **NÚKIB** (or National CERT for the lower regime) | `detected_at` | **24h** early warning · **72h** notification · **1 month** final report |

## 1. On detection — file the breach

```bash
echo '{
  "detected_at": "2026-05-31T14:00:00Z",
  "nature": "Unauthorized read of the customer table",
  "status": "detected",
  "risk_level": "high",
  "affected_subjects": 1200,
  "affected_records": 1200,
  "data_categories": "name, email, order history",
  "likely_consequences": "identity-correlation / spam exposure",
  "measures_taken": "credential rotated, access revoked, audit-chain verified",
  "nis2_in_scope": true,
  "nis2_regime": "higher"
}' | php files/anatomy/wing/bin/breach-file.php --json=-
```

**Hard rules:**

- **`detected_at` / `aware_at` MUST be ISO-8601 UTC** (`...Z` or `+00:00`). A
  local-time stamp would skew the 24h/72h/1-month math by the host offset — the
  CLI **rejects** non-UTC with exit 2. (`aware_at` defaults to `detected_at`.)
- **Set `risk_level` honestly** — it is a legal judgement, not a computation.
  `risk_level: none` **or** `status: non-reportable` ⇒ **no Art-33 clock**
  (Art 33(1): "unless unlikely to result in a risk"). Do not over-file low-risk
  events; do not under-file genuine risks.
- **`nis2_in_scope: true`** only when the event is a ZKB-regulated cyber incident
  (it adds the NÚKIB 24h/72h/30d track on top of any GDPR track).
- **Art-34(3) exception** (`art34_exception: encryption | risk_mitigated |
  disproportionate_effort`) waives the data-subject notification when lawful.

## 2. Deadline tracking & escalation

`bin/breach-scan.php` reads the per-stage `*_due_at` columns (stamped at
file-time) and emits **one CRITICAL notification per overdue, undischarged,
applicable stage** into `wing.db.notifications` (channels: wing-inbox + ntfy +
mail; the A9 `dispatch-notifications` worker pushes them). It de-dups via a
deterministic `uuid` + an `escalated_stages_json` stamp, so re-running is a
no-op once a stage has alerted.

- **GDPR Art-34 is REPORT-ONLY — never escalated.** Its "without undue delay"
  standard has no zero-hour deadline; escalating it from t=0 would alert-spam
  every high-risk filing. Its status shows in the report (§4), not as an alarm.
- **NÚKIB 30-day final report** clamps to the **end of the target month** (no
  month-overflow on short months).

**Scheduling:** run the scan hourly. Until the Pulse auto-registration lands
(deferred follow-up), wire it via cron or the launchd/systemd timer pattern, e.g.

```bash
# hourly, UTC clocks
0 * * * * /opt/homebrew/bin/php /Users/<you>/wing/app/bin/breach-scan.php >/dev/null 2>&1
```

A manual check any time: `php files/anatomy/wing/bin/breach-scan.php --dry-run`.

## 3. Discharge a stage (stops escalation)

After you actually notify the regulator/subjects, stamp the done-marker so the
scan stops alerting that stage:

- `App\Model\GdprRepository::markStage($id, 'art33'|'art34'|'nis2_24h'|'nis2_72h'|'nis2_final')`
  sets the matching `*_done_at` / `notified_*_at` column (UTC).
- Record the regulator's case id in `regulator_ref`.

## 4. Regulator report

```bash
php files/anatomy/wing/bin/breach-report.php --id=<n> --format=md    # human-readable
php files/anatomy/wing/bin/breach-report.php --id=<n> --format=json  # machine ingest
```

Renders three blocks: **Art-33** (33(3) a-d: nature + categories + counts, DPO
contact, likely consequences, measures), **Art-34** (b/c/d plain-language, or a
`skipped_reason`), and **NÚKIB** (authority by regime, 24h/72h/30d status).
Controller/DPO identity comes from `gdpr_controller_name` / `gdpr_dpo_name` /
`gdpr_dpo_contact`. The operator submits it via **Portál NÚKIB** and the
**datová schránka** (automated statutory delivery = audit P0 #8, separate work).

## 5. Business continuity / disaster recovery

Data-loss recovery is the [`restore-runbook.md`](restore-runbook.md) path
(encrypted nightly backups → `--tags restore`). Verify the audit trail after a
restore with `php files/anatomy/wing/bin/verify-audit-chain.php` (gov P1).

## 6. Roles

- **Operator** — files the breach, runs the scan/report, submits to the regulator.
- **DPO** (`gdpr_dpo_name` / `gdpr_dpo_contact`) — the Art-33(3)(b) contact point;
  owns the risk-level judgement and the supervisory-authority relationship.
