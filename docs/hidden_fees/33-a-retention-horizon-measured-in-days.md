# 33 — A retention horizon measured in days, on a ledger that grows in bytes

**Found 2026-08-29, answering "why is Wing hard to get hold of".**

The operator's report was about legibility, not disk. Measuring it with a new
reader (`tools/wing-status.py`) put a number on it that nobody had:

| | |
| --- | --- |
| `wing.db` | **1223 MB** |
| `events` | 380 248 rows, **1190 MB — 97% of the organ** |
| of which `result_json` | **921 MB** |
| of which `task_ok` alone | **657 MB** |
| largest single row | **4.1 MB** (`pazny.state_manager` introspection) |
| age of the oldest row | **36 days** |

Every Wing presenter, every Grafana panel, Bone's loop tables and the face's BFF
share that file. The organ is one table, and that table is one column.

## The fee

The estate has a retention policy. `tasks/audit-retention.yml` runs
`bin/purge-events.php`, GDPR Article 5(1)(e) storage limitation is cited in its
header, the horizon is a committed default — `wing_audit_retention_days: 365` —
and there is a gate proving the purge re-anchors the audit chain. It is a
complete, correct, tested mechanism.

**It would free nothing.** The ledger reached 1.19 GB in thirty-six days. There
is no row old enough for a 365-day horizon to touch; there never has been. The
policy is expressed in *time* and the cost is in *bytes*, and the two were never
compared, so a control that looks live has never had anything to do.

At the rate measured, the horizon's own promise is ~12 GB before the first row
becomes eligible for deletion.

## What was actually wrong

Not the horizon. The payload.

`v2_runner_on_ok` sent the entire Ansible module result for every task that did
nothing. The largest key across the sample was `invocation` — Ansible echoing
back the module's **own arguments**, which the event already carries as `task`
and `role`. The input, filed as though it were the outcome, 380 000 times.

And nothing reads it. The only consumers of `result_json` in the whole tree are
agent reports, migration payloads and DSAR records — never a task's.

## What was done

`bound_result` in `callback_plugins/wing_telemetry.py`: `invocation` goes
always, then the largest remaining top-level keys go until the result fits
16 KB. On 20 000 real rows the two biggest event types went from 230 MB to
25 MB — **89%**, and a projected ~1.3 GB/year instead of ~12.

Every omission is named in the row, in an `_omitted` key carrying what went, how
many bytes, and the cap that caused it. That half is not a nicety: a record that
quietly lost its `stdout` is indistinguishable from a task that printed nothing,
which is this estate's signature defect wearing a smaller hat.

Gate: `tests/anatomy/test_the_ledger_does_not_carry_the_arguments.py`, retro-
verified against five broken states including dropping silently and bounding
before scrubbing.

## Not closed

**The existing 1.19 GB stays.** `result_json` is one of the columns
`App\Model\AuditChain` hashes, so rewriting old rows to shrink them is exactly
what the tamper-evident chain exists to detect — and it would be right to
report it. History is not compressible here by design. Only new rows are
bounded; the old ones age out under the horizon, slowly, as intended.

**Nothing compares a retention horizon against a growth rate.** That is the
generalisable half and no gate is proposed for it, because the honest form of
the check is "will this policy ever fire", and the estate has no place that
knows a policy's expected first firing. `wing-status.py --cost` at least makes
the number askable.
