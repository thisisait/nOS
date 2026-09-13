# Gates — a check that cannot fail is not a check

A gate exists to go red. A gate that can report success **without having
examined the thing it claims to examine** is worse than none: it converts
*"we did not look"* into *"we looked and it was fine"*, and the second stops
anyone looking again.

## 1. The rule in one sentence

A check **must** fail when it did not run, and **must** be able to tell that
it did not run. The second half is where every case below actually goes wrong.

## 2. The two symmetric failure modes

**1. Missing evidence read as success.** The check did not run, the field was
absent, the file was not found — and the gate treated that as a pass. An
unreported check is a **FAIL**, always. Absence of a result is not a result.

**2. A green check that did not run against what it claims.** The check ran,
went green, and was pointed at the wrong thing: a stale build artifact, a
skipped code path, a dry-run that never reaches the real one.

They are the same defect from opposite sides. An **accidental** false green
(a stale artifact) is an operational slip: the next clean run exposes it. An
**architectural** false green manufactures the wrong answer every time; it
**shall** earn a redesign, not a checklist item.

Measured cases of both:

- Upgrade-engine dry-run short-circuited before handlers and reported success
  (memory `upgrade-engine-apply-path`).
- A DB-blind healthcheck certified miniflux healthy while every request 500'd
  ([`hidden_fees/02`](../../docs/hidden_fees/02-db-blind-healthchecks.md)).
- A sibling-repo guard passed twice against a stale `dist/` (KEAP, 2026-07-20).

## 3. The shape underneath all of them

> **the check measured a different layer than the one that fails.**

- dry-run measured the *plan* layer; *apply* had never run
- healthcheck measured *HTTP*; the *database* was broken
- a unit test of `buildVersion()` would have measured the *function*; the
  *bundler* dropped `__dirname` in the ESM bundle and `/api/health` died.
  Caught because the test called the **endpoint**.

A test **shall** run where the caller calls, not where it is convenient to
call. A test one layer below the failure is a test of something else,
reported under the name of the thing you care about.

## 4. Where to spend the attention

> **the more systematic the cause, the less likely anyone notices it without
> going looking.**

An accidental false green shows up on the next clean run. An architectural
one looks like normal operation indefinitely.

This is the same test that admits an entry to
[`hidden_fees/`](../../docs/hidden_fees/README.md) — *nothing is failing and
nobody is looking*. A hidden fee is what a false green lets you keep
believing.

## 5. Rules

- A gate **must** fail closed. No result, no evidence, no artifact ⇒ fail.
  Never skip-as-pass.
- A gate **must** land with the negative case exercised. An untested gate is
  a claim, not a check.
- A gate **shall** assert on substance, never on silence. Do not gate on "no
  warnings", "empty stderr", or "log looks clean".
- A gate **shall** pin what it ran against (version, hash, or path).
- A gate **must** not be able to damage what it guards. Run against a
  throwaway copy, not the live thing.
- The first hard run of a gate tests the gate, not the subject. Treat its
  first green as unproven until it has gone red on purpose. (2026-07-21:
  nOS producer gate never passed `--schema`; KEAP consumer gate passed
  `KEAP_DATA_DIR` to every command except schema create.)
- A skip **must** not outlive its reason. Record the trigger that makes it
  mandatory; otherwise "temporarily skipped" is missing evidence read as
  success with a comment.

## 6. The silence trap, concretely

A gate **shall** assert measured outcomes, not the absence of noise.

Self-model prune (2026-07-20) correctly refuses and says so; that warning
**is** the guard working. The assertions are `removed == 0` and
`danglingAnchors == 0` — they stay true whether or not the correct path is
chatty.
