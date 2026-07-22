# 07 — Operator-facing text that outlived the mode it was written for

**Status:** OPEN. One instance paid (`d8c7e63c` — the blank-reset ENTER box +
completion banner); the class is unpaid and the estate is not yet swept.

## The fee

Every `debug:`, `pause: prompt:`, `fail_msg:` and banner in the playbook was
written when the run had **one** shape. It states, as flat fact, things that
were true of that shape: *"Playbook now continues with clean installation"*,
*"After reset the playbook reinstalls everything"*, *"4 Docker stacks"*,
*"blank"*. Then the ladder arrived — `remove=none|data|deep|all`, `--leave`,
`-y` — and each of those sentences became conditionally false, with **no
mechanism anywhere that notices**.

The text is not executable, so nothing type-checks it, no gate covers it by
default, and the playbook behaves perfectly while telling the operator
something else. First live proof (2026-07-22, `nos --remove=all --leave
--confirm`): the machine tore the estate down and ended the play exactly as
designed, while the banner announced a blank reset that would continue into a
reinstall. Two sentences, two independent falsehoods, zero failures.

## Why nobody was looking

The C5.1 rewording *did* pass over this file — it corrected the ENTER box and
stopped there, and the gate that pinned the box (`G-7`,
`test_blank_reset_confirmation_accuracy.py`) pinned only what the rewording had
already touched. **A gate written around an existing fix certifies the fix, not
the class.** The closing banner sat three screens below, unpinned, saying the
old thing — and every green run since agreed with it.

The general shape, and the reason this is a *fee* and not a bug: an operator
reading a false-but-plausible message does not file a report. They adjust their
mental model to match the lie. The cost is paid later, by someone acting on a
belief the software gave them for free.

## The rule

**Operator-facing text is a claim about the current run. If a claim's truth
depends on a flag, the text must read that flag — or not make the claim.**

Corollaries, each earned on 2026-07-22:

- **Pin both ends of a ceremony.** An accurate opening and a lying closing are
  the same defect; a gate on one of them measures neither.
- **Announce expected silence.** `flush-deep` prunes for minutes with no
  output. Silence the operator was warned about is progress; unannounced
  silence is indistinguishable from a hang — and the operator's correct
  response to a hang (Ctrl-C) is the wrong response to progress.
- **Do not let a gate fail on prose about a task.** Both gates touched that day
  first went red on *documentation* naming the thing they police. The fix an
  author reaches for is to delete the sentence, which is exactly backwards:
  skip comments, assert on the live template.

## What paying this off looks like

Not "grep for the wrong sentence" — that is what was already done, once, per
instance. The class closes with a **sweep plus a gate**:

1. Inventory every operator-facing string emitted by the removal/run-mode path
   and by `main.yml`'s phase banners; for each, ask which flag its truth
   depends on.
2. Fix each to read that flag (or drop the claim).
3. A gate that fails when a message in these files asserts a
   mode-dependent fact **unconditionally** — the enforceable version is a
   deny-list of claim phrases (`continues with clean installation`,
   `reinstalls everything`, a bare level name, hardcoded counts) that must
   appear only inside a conditional expression. Break-test it by planting one
   flat sentence.

Scoped into the hidden-fees payoff workflow. **Operator is feeding live
occurrences as they surface across runs** — each one that arrives is a string
to fix and, more importantly, a datapoint on what the deny-list must cover.

## Occurrences so far

| Where | Said | True when |
|---|---|---|
| `blank-reset.yml` completion banner | `BLANK RESET COMPLETE … continues with clean installation` | `remove=data` **and** `leave=false` — **PAID** `d8c7e63c` |
| `blank-reset.yml` ENTER box | `After reset the playbook reinstalls everything` | `leave=false` — **PAID** `d8c7e63c` |
| `blank-reset.yml` completion banner | `4 Docker stacks` (hardcoded; the down-loop covers 9) | never — **PAID** `d8c7e63c` |
| _(operator-reported, pending)_ | | |
