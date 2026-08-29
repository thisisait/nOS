# Ponytail debt — the shortcuts taken on purpose

Collected 2026-08-29 by `/ponytail-debt`. Every row is a `ponytail:` comment in
the source: a simplification someone chose deliberately, with the ceiling it
accepts and the trigger that should reopen it.

**This file is a copy, not the source.** The markers live next to the code they
govern, which is where a reader meets them; regenerate with:

```bash
grep -rnE '(#|//|\*) ?ponytail:' . --exclude-dir=.git --exclude-dir=node_modules \
  --exclude-dir=vendor --exclude-dir=.svelte-kit --exclude-dir=build \
  --exclude-dir=worktrees --exclude-dir=__pycache__
```

A row here that no longer matches the source means this file is stale, not that
the debt was paid.

---

## `files/anatomy/scripts/agent-run-lock.sh:108`

All-or-nothing slot claim rather than a ticket queue.

- **Ceiling:** two claude-CLI acquirers can livelock, trading slots.
- **Upgrade:** add a ticket slot (monotonic counter) — *only* if that is ever
  observed. Both sides are bounded by `wait_s` and refuse loudly meanwhile, so
  the failure is noisy rather than silent.

## `files/anatomy/wing/app/AgentKit/Tools/McpKeapTool.php:82`

One tool holding `keap.read` + `keap.write`, where `mcp-wing` is split into
read and write planes.

- **Ceiling:** an agent that wants KEAP read cannot have it without write.
- **Upgrade:** split into two planes the day an agent wants read alone.
- Worth knowing: until 2026-08-28 this asked only for `keap.read` and served
  every path in its POST allowlist anyway — a read scope that could write, the
  same defect the Wing split closed.

## `files/anatomy/wing/app/AgentKit/Outcome/GateOracle.php:29`

Peak scoring by the verdict's three-valued rank (`indeterminate 0 < fail 1 <
pass 2`).

- **Ceiling:** cannot tell "3 of 5 judges passed" from "1 of 5"; the client does
  not expose the per-run rows behind the sealed verdict.
- **Upgrade:** add a reader for `loop_judge_runs` if the peak rule ever needs
  that resolution — explicitly **not** a second judge runner.

## `files/anatomy/wing/app/Presenters/LoopEditorPresenter.php:143` — `no-trigger`

Regex over one committed literal instead of parsing the Python.

- **Ceiling:** a spelling change in the source enum breaks the read.
- **Upgrade:** none named. The marker points at
  `test_the_harness_toggle_defaults_off.py`, which imports the real module — so
  drift goes red there before this page can quietly show nothing. That is a
  guard, not a trigger, and it is why this row is the one that can rot: nothing
  says when to stop accepting it.

---

**4 markers, 1 with no trigger.**

Nothing was added on 2026-08-28/29 despite a large branch — `mcp-loop`,
`awaiting-operator` and the deliverable check were written in their target shape
rather than as shortcuts. A day that adds a lot of code and no debt markers is
worth a second look, not a celebration: the risk is not that the shortcuts were
unmarked but that they were taken and nobody noticed they were shortcuts.
