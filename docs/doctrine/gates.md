# Gates — a check that cannot fail is not a check

A gate exists to go red. Everything below follows from that: a gate that can
report success **without having examined the thing it claims to examine** is
worse than no gate, because it converts *"we did not look"* into *"we looked and
it was fine"* — and the second one stops anyone from looking again.

## The rule in one sentence

**A check must fail when it did not run — and must be able to tell that it did
not run.** The second half is the hard one, and it is where every case below
actually goes wrong.

## The two symmetric failure modes

**1. Missing evidence read as success.** The check did not run, the field was
absent, the file was not found — and the gate treated that as a pass. An
unreported check is a **FAIL**, always. Absence of a result is not a result.

**2. A green check that did not run against what it claims.** The check ran, went
green, and was pointed at the wrong thing: a stale build artifact, a skipped code
path, a dry-run that never reaches the real one. This is the harder half, because
everything looks correct — there is a passing test with a plausible name.

They are the same defect from opposite sides — but they are not equally
dangerous. An **accidental** false green (a stale artifact, a build that did not
rerun) is an operational slip: it happens once and the next clean run exposes it.
An **architectural** false green is a design that manufactures the wrong answer
every time, and no amount of care at the call site helps. Weight them
accordingly; the second kind earns a redesign, not a checklist item.

nOS has been bitten by both:

- **The upgrade engine's dry-run was a false-positive verify** — it short-circuits
  before handlers, so the apply path had never actually run while reporting
  success (`docs/plans/…`, memory `upgrade-engine-apply-path`).
- **A DB-blind healthcheck certified miniflux healthy for 19 hours** while every
  request 500'd; the STRICT bring-up gate passed it. Green ≠ working
  ([`hidden_fees/02`](../hidden_fees/02-db-blind-healthchecks.md)).
- **A sibling repo's guard test passed twice against a stale `dist/`** — the
  disabled version failed typecheck, the build silently did not rebuild, and the
  suite ran the old bundle. A test asserting it catches a regression, catching
  nothing (KEAP, 2026-07-20).

## Rules

- **Fail closed.** No result, no evidence, no artifact ⇒ fail. Never skip-as-pass.
- **Prove the gate can fail.** A gate lands with the negative case exercised —
  break the thing on purpose once and watch it go red. An untested gate is a
  claim, not a check.
- **Assert on substance, never on silence.** Do not gate on "no warnings", "empty
  stderr", or "log looks clean". Correct behaviour is often noisy, and a gate on
  quiet fails the moment a correct fix starts announcing itself.
- **Pin what the check ran against.** Version, hash, or path — so a stale
  artifact cannot masquerade as a fresh pass.
- **A gate must not be able to damage what it guards.** Run against a throwaway
  copy, not the live thing.

## The silence trap, concretely

The rule that reads as pedantic until it bites: **gate on measured outcomes, not
on the absence of noise.**

Live case (self-model, 2026-07-20): a per-uid prune guard correctly refuses to
delete and says so —

```
uid 'nos-docs' contributed 0 files this pass but has N mirrored object(s)
  — refusing to prune
```

That warning **is** the guard working. A gate that failed on the presence of
warnings would fail on its own correct fix. The right assertions are the
measured ones — `removed == 0`, `danglingAnchors == 0` — which stay true whether
or not the correct path is chatty.
