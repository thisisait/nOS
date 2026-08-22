# The security floor — what a pending finding is waiting for

> Status: doctrine, opened 2026-08-22 after a four-design panel. Most of what the
> panel proposed is **refused** here, with the reason, because the refusals are
> the durable part.

## The rule

**Severity picks what must be NOTICED now. What a row is BLOCKED ON picks
whether a release boundary means anything to it.**

Three lanes, read with `tools/rem-status.py --floor`:

| lane | rule | measured 2026-08-22 |
| --- | --- | ---: |
| act now | `severity` ∈ {CRITICAL, HIGH} | 12 |
| waits for a tag | below HIGH **and** `remediation_type: version_bump` | 15 |
| waits for nobody | below HIGH, anything else | 30 |

A deferral **never touches `status`**. `tools/rem-status.py` filters strictly on
`status == "pending"` and `tools/discovery-scan.py` pattern-matches the literal
strings, so a new status value would delete deferred rows from the one tool
CLAUDE.md tells every operator and agent to consult first.

## Why the third lane is the whole point

The roadmap row asked to "act on CRITICAL/HIGH, batch the rest to a release
boundary", on the arithmetic that `rem-status` prints `+45 pending below HIGH`
of 54 — the "83%" headline.

Split by what each row is blocked on, that population is not one thing:

```
below HIGH, waits for a tag      15   version_bump
below HIGH, waits for NOBODY     30   of which 21 are config_change
```

A release moves pins. It does nothing whatever for a config change. Deferring
those 30 to the next tag would **relabel actionable work as upstream-gated** and
conserve no effort at all — while removing them from view for a quarter.

Two more measurements that cut against the original framing: 40 of the 45 rows
below HIGH were **found this month** (4 in July, 1 in April), so "stale backlog"
is not what this is; and only ~20 of 57 pending rows are version bumps at all.

## What was refused, and why — this is the load-bearing part

**A `reachability` schema field, and a controls catalog.** Two designs proposed
one; both are right that reachability, not severity, is the axis that predicts
exposure on *this* estate. Refused for now on their own evidence: nothing has a
live-probed verdict today, so a floor gated on one **defers approximately
nothing on day one** and grows only as fast as probe work lands. The design is
sound and premature; it is not lost, it is waiting for probes to exist.

**A `phase` sub-state machine under `pending`.** Elegant, additive, and it names
a real gap — there is no state for "the estate says this is already done", which
is exactly what `discovery-scan` now reports for REM-188 and REM-204. Refused
because it requires the nightly LLM to emit reliably-structured fields, and the
design's own failure analysis is the reason: a malformed block on a big CVE
night either loses a scan cycle or degrades silently, and this estate has
already paid for that shape once (`20-cve-drift-check.sh`, two ISO-8601
spellings, a hook that printed nothing at exit 0 for months).

**A mechanical severity-vs-own-text contradiction check.** Proposed as the cheap
win: flag any row below HIGH whose `remediation_detail` quotes a CVSS ≥ 7.0.
**Built and disproved the same hour.** It finds three pending rows; all three are
correct as filed. REM-143 quotes 9.6 and says in its own first line "NOT a CVE";
REM-206 quotes 10.0 for an unpublished-image finding. The quoted number belongs
to something *else* the text discusses. Deliberate down-rating against nOS
context is good practice this estate already does on purpose — REM-208 is filed
HIGH "on nOS context alone" against a vendor CVSS of 9.9 — and a check that
cannot tell that apart from a misfiling manufactures work.

**Non-negotiable #5 — "an advisory that defeats the control a deferral relies on
auto-escalates" — as an automation.** All four designs refused it independently.
Deciding whether a new mechanism defeats a cited control is prose judged against
prose. It stays a human call; what the estate can do is make the judgement
*legible* after the fact. Stop promising the automation.

## A refusal added later, on the same evidence standard (2026-08-22)

`docs/idea/19-fable-review-2.md` §3.1(a) proposed the cheap half of the vacuity
problem: *"when no judge in the set has an `oracle_paths` overlap with the diff,
the verdict is `nothing objected`, not `pass`"*. It was carried into the Q2 plan
at ~1 hour and queued for the night the loop would first meet it.

**It is not implementable as stated, because `oracle_paths` do not mean what the
rule assumes.** They are not a declaration of what a judge COVERS — they are the
deny-list input `budget.py:220` uses to stop the loop editing a judge's own
source while being graded by it. `judges.py:238` refuses to load a judge without
them for exactly that reason: *"a judge that declares no oracle is a judge whose
own source the loop may edit while being graded by it."*

Read them and it is obvious: `ansible-lint` declares `['.ansible-lint',
'.yamllint']` — its own config files, not the thousands of YAML files it lints.
`pytest-anatomy` declares `tests/anatomy/**` — the tests, not the tree they
assert about.

So the rule would mark almost every legitimate diff `nothing objected`, since a
change to `roles/**` or `default.config.yml` overlaps no judge's own machinery.
It happens to give the right answer for a version bump, which is the case it was
derived from, and the wrong one everywhere else.

What the rule actually needs is a per-judge COVERAGE declaration, which no judge
has today. That is a new field and a real design question — not an hour.

## What is still owed

- The three lanes are **descriptive**. Nothing yet stops a row in lane 2 from
  being deferred past a tag that never comes: releases here have slipped 3–4×,
  and v0.11 has been drafted since 2026-08-19. A backstop should reuse the
  estate's own staleness cadence (the drift baseline complains past 14 days)
  rather than invent 90 days.
- **`loop-requires-operator` is a prerequisite, not a sibling.** If this floor's
  escalation logic ever ships as a loop-authored `gate-add`, it inherits the
  unattended-merge hole: `OPERATOR_REQUIRED_INTENTS` holds only `gate-add` and
  `loop-pr.py`/`loop-review.py` never read `requires_operator`. The roadmap lists
  them as siblings; they are not.
- **The canary route** is the cheapest thing anyone proposed and it belongs to
  `sec-p3`, not here: a token rendered behind the same `authentik@file`
  middleware as the 13 forward-auth services, reachable **only if that control
  fails**. It cannot prove a gate holds — only a fault-injection probe does that
  — but it reports continuously, costs about what `sec-p3` already costs, and
  needs no maintenance window. REM-048's exact shape, watched for free.
- REM-212 stays in lane 1 and always will. It is CRITICAL, reachable, and
  unfixable — both named fix versions do not exist. Its disposition is
  `sec-rem-212-disposition`, and it is a decision, not a lane.
