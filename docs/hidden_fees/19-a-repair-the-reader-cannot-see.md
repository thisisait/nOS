# 19 — A repair the reader cannot see

**Found 2026-08-22, while trying to diagnose a red that had already been fixed.**

`tools/red-status.py` reported the Sunday restore drill as failing for **six
days**. The drill had been green since day one of those six.

## What actually happened

```
2026-08-16 07:38:18  keap-db: fetching 2026-08-16/keap-db.gz
2026-08-16 07:38:28  keap-db: MISSING              ← ten seconds
2026-08-16 07:38:28  wing-db: fetching …
2026-08-16 07:38:34  wing-db: OK                   ← 74 MB in six seconds
2026-08-16 07:38:34  ==== nOS restore drill FAILED ====

2026-08-16 11:07:56  keap-db: OK (1710/5084/365)
2026-08-16 11:08:08  ==== nOS restore drill OK ====   ← same morning

2026-08-19 17:09:41  keap-db: OK (1711/5084/367)
2026-08-19 17:09:48  ==== nOS restore drill OK ====
```

The failure was transient: a 346 MB `keap-db` fetch aborted after ten seconds
while the 74 MB `wing-db` fetch beside it completed in six. The operator re-ran
the drill by hand four hours later and it passed. It passed again three days
after that.

Verified independently before touching anything — the object was there all
along (`s3://backups/2026-08-16/keap-db.gz.enc`, 346,857,696 bytes, written
03:02:22), it downloads intact today, and it decrypts with key #0 of the ring.

## Why the reader kept saying red

`failing_jobs()` reads `pulse_runs` and takes each job's **most recent run**.
A manual invocation leaves no `pulse_runs` row. So the newest row for
`backup:backup-restore-drill` was — and still is — the 2026-08-16 failure.

For a **weekly** job that is up to seven days of reporting a defect that was
repaired within four hours, and the repair is invisible *precisely because the
operator did it himself*.

## Why this is a fee and not a bug

Nothing was broken. The drill worked, the backup worked, the object was intact,
the key ring opened it, and `~/.nos/backup-verify.json` had said

```json
{"backup_date": "2026-08-19",
 "artifacts": [{"name": "keap-db", "success": true, …},
               {"name": "wing-db", "success": true, …}]}
```

for three days. **Nothing read that file.** The schedule was standing in for the
outcome, and the estate has a name for that mistake — a success marker written
by the attempting code — but this is its mirror image: an outcome nobody reads,
so the *attempt record* becomes the verdict by default.

## What it cost, and it is more than six days of noise

The morning this was found, `docs/Q2-2026-plan.md` had just been written with
**"diagnose the restore drill" as item 0 of the quarter**, on the stated ground
that a red drill gates the `sec-p1` HKDF blank — you do not mint new credentials
while the estate cannot prove it can restore under the old ones. That reasoning
is correct. Its premise was false. **The quarter's largest security item was
scheduled behind a blocker that had cleared three days earlier**, and the plan
said so in writing because every reader in the chain, human and agent, asked the
one tool CLAUDE.md tells them to ask first.

An alarm that cries wolf is not merely ignorable — it reorders work.

## Fixed

`red-status.py` gained `restore_drill()`, which reads the drill's own artifact,
and `reds()` now compares the two timestamps. When the artifact is newer, green
and not stale, the line becomes:

> `backup:backup-restore-drill` last SCHEDULED run failed (6 d ago) but the drill
> has passed since — backup-verify.json says 2/2 ok for backup set 2026-08-19
> (2 d ago). Not red; the next scheduled run will clear the row.

Both facts, neither hidden. The job row is still named, because a drill that
never runs again on its schedule is a different finding and `stale` (14 days)
still catches it.

Gate: `tests/anatomy/test_a_manual_repair_is_visible.py`.

## What is still owed

- **This is one job.** Every other Pulse job has the same property: repair it by
  hand and `red-status` keeps the failure until the next scheduled run. The
  restore drill is fixed because it happens to write an artifact; nothing
  generalises that. A job that writes no verdict file cannot be exonerated at
  all.
- The drill's own failure message conflates three causes — a missing object, a
  failed decrypt and an empty result all print *"no object at DATE (or it
  decrypted to nothing)"*. That sentence sent this investigation looking for a
  missing backup for the first twenty minutes. `fetch()` knows which of the
  three it hit; it should say.
- Nothing retries a transient fetch. Ten seconds on 346 MB is not a verdict on
  the backup, and a weekly job gets one attempt per week.
