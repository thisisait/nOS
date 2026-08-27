# 07 — Operator-facing text that outlived the mode it was written for

**Status:** OPEN as a class. Two instances paid — `d8c7e63c` (the blank-reset
ENTER box + completion banner) and the post-ready tick label (2026-08-27,
item A below). The class is unpaid: the estate is still not swept, and nothing
notices when the next sentence outlives its mode.

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
4. The *present-tense* half (occurrences A and B below): every task that can
   run longer than a tick of operator patience announces its expected duration
   **before** it starts, and no progress line may describe work it is not
   doing. Candidates found so far: the `flush-deep` prune, the first
   full-corpus KEAP embed, GitLab cold init.

Scoped into the hidden-fees payoff workflow. **Operator is feeding live
occurrences as they surface across runs** — each one that arrives is a string
to fix and, more importantly, a datapoint on what the deny-list must cover.

## Occurrences so far

| Where | Said | True when |
|---|---|---|
| `blank-reset.yml` completion banner | `BLANK RESET COMPLETE … continues with clean installation` | `remove=data` **and** `leave=false` — **PAID** `d8c7e63c` |
| `blank-reset.yml` ENTER box | `After reset the playbook reinstalls everything` | `leave=false` — **PAID** `d8c7e63c` |
| `blank-reset.yml` completion banner | `4 Docker stacks` (hardcoded; the down-loop covers 9) | never — **PAID** `d8c7e63c` |
| `blank-reset.yml` ENTER box | `Docker images + build cache (remove=deep)` while running `remove=all` | `remove=deep` — **PAID** `f230a946` |
| `blank-reset.yml` ENTER box | `remove=deep also clears the cache` | `remove=deep` — **PAID** `f230a946` |
| `blank-reset.yml` ENTER box | `~/nos/tenants/** user files` under **"Will remain"** during `remove=all` — the one level that deletes them | `remove != all` — **PAID** `f230a946` |
| `main.yml` sudo `vars_prompt` | `Press Enter to skip (those tasks will fall back to manual mode)` — `become` tasks hard-fail, they do not skip | never; cost a live all-on install at the first Homebrew task — **PAID** `f230a946` |

The fourth row is the expensive kind: the other three misname a level, but that
one told the operator an action was **safe** when it aborts the run. A gate
pinning the *literal* `remove=deep` (G-7, pre-`f230a946`) had certified two of
these — **a gate written around a fix certifies the fix, and can encode the very
lie it exists to catch.** It now asserts the line renders the running level.

### Occurrences of the sibling kind: text about *what is happening now*

The four above are sentences that were true of an older mode. These two are
different and, for an operator watching a live run, worse — the log describes
the wrong *present*. Both surfaced on the 2026-07-22 all-on install
(`failed=0`, 63 containers), both while nothing was actually wrong.

**A. Post-ready no-op ticks print as polling. PAID 2026-08-27** — the label is
now conditional on `_wait_done` and says `already ready — no-op`. The account
below is kept because it is the reasoning, not the state.

`wait-stacks-healthy.yml` loops
the full time budget by construction — a `when:` on a *looped* `include_tasks`
cannot short-circuit, so the early exit lives inside `health-tick.yml`, where
every task is gated on `not _wait_done`. Correct. But `loop_control.label`
still renders `tick N/36 — <stacks>` for each no-op iteration, so ~80 ticks
scroll past in two seconds and read as a spin. Verified not a spin: real
waiting ticks sit 16–18 s apart (20:22:16 → 20:22:34). The label should say
what the iteration *is* — `already ready, no-op` — instead of repeating the
stack list it is no longer polling.

**B. A long task's banner arrives minutes late, so the log names the wrong
current task.** `keap-embed-sync.py` demonstrably started at 20:52:44 (its
AnsiballZ tmp dir timestamp; the process was live and Ollama busy at 20:55),
but the `Kick keap-embed-sync` TASK banner reached `~/.nos/ansible.log` only at
20:58:05. For those ~5 minutes the last logged line was the *previous* task's
one-shot debug summary — so the log said we were parked on a `debug:` while a
full-corpus embed ran. The operator read it, reasonably, as a hang on what
should be "a fast sed/awk action".

**Mechanism for B: NOT DETERMINED.** Ansible normally writes the banner at task
start, and every other task in this run logged promptly. Rather than guess, the
evidence is recorded here: task start 20:52:44 (tmp dir + live process), banner
20:58:05, same play, same pid `p=23662`. Investigate before fixing — and do not
ship a remedy that would *appear* to cure it, per the preflight lesson in
[`tests/anatomy/test_mount_preflight_diagnosis.py`](../../tests/anatomy/test_mount_preflight_diagnosis.py).

Independent of the cause, the run had **no way to say "this will take
minutes"** — the same defect as the unannounced `flush-deep` prune. A first
full-corpus embed after `remove=all` (every vector deleted) took ~10 minutes and
announced nothing at all.

| `pulse-run-agent.sh` `_post_wing_event` | `WARN: Wing event POST returned HTTP ` + curl stderr debris (a caret) presented as the status — while the run exited 0 with ZERO events landed (2026-08-17 surveyor, $0.96) | never — the "code" was `tail -n 1` of merged stderr; **PAID** 2026-08-18: WARN validates 3-digit codes and names curl's exit, and a run whose audit POSTs failed exits 2 (gate `test_wing_event_post_failure_is_not_silent.py`) |
| _(operator-reported, pending)_ | | |
