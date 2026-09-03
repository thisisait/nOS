# 09 — Hidden fees

**Status: a ledger, permanently open. The tally MOVES — ask `ls
docs/hidden_fees/` and its README index; a number copied here was 31 entries
stale within three months.**
**Detail:** [`docs/hidden_fees/`](../hidden_fees/) — one file per fee, kept
because each carries the reproduction that found it.

## What a "fee" is

A cost the estate pays that nobody decided to pay. Not a bug report — a bug is a
thing that broke. A fee is a thing that **works**, and charges for it somewhere
nobody is looking.

They are kept separately from plans on purpose: a plan describes work someone
intends to do; a fee describes a debt that accrues whether or not anyone intends
anything.

## The ledger

| # | fee | state |
|---|---|---|
| 01 | Role render path is create-only; a disabled service keeps its override | open |
| 02 | STRICT bring-up believes a healthcheck that never touches the DB | open (miniflux only) |
| 03 | Leading-digit slugs are illegal KEAP node ids | open |
| 04 | `docs/systems/**` drifts from the services it describes | open |
| 05 | KEAP/face host deprecation | **closed 2026-07-21**, on the date it said |
| 06 | Removal guard drifts from the deploy gate | **closed 2026-07-22** |
| 07 | **Messages that outlive their mode** | **OPEN** — 4 instances paid, class unpaid |
| 08 | **An empty stack reads as success** | **OPEN** — and now partly visible |
| 09 | Untuned ANN index (`libsql_vector_idx` with no parameters) | open |
| 10 | The cortex organ cannot recall | open |
| 11 | Vendored cortex copies drift from KEAP | open |
| 12 | `nos/keap:{{ version }}` is a tag, not a version | open |
| 13 | Per-user DB files without per-user enforcement | open |

## The two that matter most, and why they are one thing

**07 — messages that outlive their mode.** A message written for one situation
keeps being emitted in another, where it is false. Four instances paid; the
*class* is unpaid, and it carries an UNDETERMINED mechanism, recorded
deliberately without a guessed remedy.

**08 — an empty stack reads as success.** `stack-health-probe.py` reports
`0/0 ready` and exits 0 when a stack has no containers. That is why the Linux
wet-test was green for weeks with **no infra rendered at all**.

07 grew a wider rule that 08 is an instance of:

> **A step that cannot do its job must not exit 0.**

Three instances on the books: the drift hook that parsed nothing, its
notification that delivered nothing, and the Linux wet-test passing `0/0 ready`.

## What v0.10-beta paid, and what it did not

The release was named after this class and closed several instances —
delivery stamping on failure, a scan stamping freshness without scanning, a
daemon four converges older than its code, 175 swallowed failures against 2
asserts.

**08 is now visible rather than fixed.** The Linux run reaches `ok=550` (from
226) and fails honestly at the smoke gate. One claim in that document is
therefore withdrawn: *"the wet-test never tested what it claimed"* was too
strong — it tested little because the run died early, not only because the probe
was tolerant. The probe weakness is unchanged.

## The rule this ledger enforces

**Record the fee even when the remedy is unknown.** Fee 07 carries an
undetermined mechanism on purpose: a guessed remedy would have closed the entry
and left the cost. An honest open entry is worth more than a confident wrong one.
