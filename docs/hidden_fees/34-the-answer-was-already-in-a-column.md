# 34 — The answer was already in a column, and the new reader did not ask

**Found 2026-08-29, within a day of [fee 32](32-the-dashboard-counted-finishing-as-succeeding.md), building the dashboard next to it.**

`27-pulse.json` was written to give the estate's scheduled-job organ a surface —
56 000 runs of `pulse_runs` with nothing in Grafana reading them. Its central
panel ranks jobs by failure rate. The first draft classified any non-zero exit
code as a failure and produced this:

| job | runs | failed | |
| --- | --- | --- | --- |
| `discovery:contradiction-scan` | 24 | **16 — 66.7%** | top of the list |
| `loop:propose` | 9 | 3 — 33.3% | |
| `gitleaks:nightly-scan` | 30 | 1 | |

Every one of those "failures" was the job working. `pulse_jobs` has a column,
`findings_exit_codes`, holding the codes a job uses to mean *I found something*:
`[1]` for the contradiction scan and gitleaks, `[1,3]` for `loop:propose`. Read
with it, the same thirty days are `0 failed, 16 found`, and the actual failures
— `alert-relay:relay-firing` at 157, `wing:audit-chain-verify` at 4 — stop
sitting below a healthy detector.

## Why this is not just fee 32 again

Fee 32 was a panel asking the wrong question because nobody had written down the
right one. This is worse and cheaper to avoid: **the right question was already
written down, in the schema, in a column populated for every job that needs it,
months before the panel existed.** The new reader simply did not ask.

That is the shape to watch for. A surface built over a mature table inherits
every distinction that table's authors bothered to encode, and the default
failure is not to contradict them — it is to never look. `exit_code <> 0` is
such an obvious predicate that it does not feel like a modelling decision, which
is exactly why it went in unexamined.

## What was done, 2026-08-29

Both panels that judge an exit code now join `pulse_jobs` and split `found` from
`failed`; the sort is on `failed`. The dashboard's own header says so, because a
number that differs from a naive count needs its reason where the doubt happens.

Gate: `tests/anatomy/test_a_finding_is_not_a_failure.py` — any query in this
dashboard that branches on `exit_code <> 0` must mention `findings_exit_codes`,
and the match must be comma-anchored so `[1]` cannot claim exit 11 and `[13]`
cannot claim exit 1. Retro-verified against the first draft and against an
unanchored `LIKE`; the second mutation passed on the first attempt with a
one-job fixture, which is why the fixture now runs the trap in both directions.

## Not closed

The gate covers one dashboard. Nothing stops the next surface over
`pulse_runs` — a face view, a reader, a notification rule — from making the same
default assumption, and a gate per consumer is the wrong answer. The right one
is a shared predicate somewhere both SQL and PHP can reach, and there is no such
place today. Filed rather than built: two consumers is not yet a seam.
