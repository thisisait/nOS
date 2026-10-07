<!-- GENERATED from state/genome/task-types.yml by tools/task-types-render.py — do not edit by hand. -->
# AGENTS.md — the task-type contract

Every row on the board carries a **`task_type`**. A row is a *claim*; its
task_type is the tiny contract for HOW to work it. Read your row's type below,
reach for its tools, and end it with its evidence — nothing more.

This page is the task-type contract. The full estate reference is [CLAUDE.md](CLAUDE.md); the
machine-readable source of this table is
[`state/genome/task-types.yml`](state/genome/task-types.yml). Adding or changing a type is a
**proposal** through the loop, not a free edit.

**Before anything else, read "Working in nOS" at the top of
[CLAUDE.md](CLAUDE.md)** — the charter every agent here works under; it is kept
in that one place.

## Three invariants that outrank every task type

Quoted from [CLAUDE.md](CLAUDE.md) at render time.

1. Success is written by a reader, not by the code that did the work — and not by your own report. Say what you verified and what you did not.
2. A fix ships with the gate that would have caught it, and the gate is shown red against the broken state.
3. This checkout is the **source**. A deployed nOS runs from elsewhere on the host (`~/stacks`, `~/wing`, `~/keap/src`, `~/face/src`, launchd/systemd organs); only a converge moves source into runtime. So a git ref answers "what is in the repo", never "what is running"

## The types

### `investigate` — Read-only. Find something out and report it; change nothing.

- **tools**: `read`, `grep`, `Explore`, `tools/*-status.py readers`
- **writes**: none · **agent-run**
- **done**: findings as file:line + the claim + its evidence; zero edits made.

### `code-fix` — Fix a defect at its ROOT (the shared function, not each caller).

- **tools**: `read`, `grep`, `edit`, `bash`, `pytest`
- **writes**: code · **agent-run**
- **done**: the pinning gate is GREEN and was shown RED against the pre-fix state (a gate you cannot fail on the broken tree does not pin anything); committed with the gate.

### `seed-edit` — Change one row / seed file (a roadmap or dtt row, a *.seed.yml).

- **tools**: `tools/roadmap-update.py`, `tools/roadmap-seed.py`, `edit`
- **writes**: data · **agent-run**
- **done**: a READER (roadmap-status / the seed's loader) shows the new value.

### `review` — Adversarially verify a claim — try to REFUTE it, not confirm it.

- **tools**: `read`, `grep`
- **writes**: none · **agent-run**
- **done**: a verdict (CONFIRMED | REFUTED) with a concrete failing-or-passing scenario.

### `design` — Produce a spec or doctrine a builder can execute; write no code.

- **tools**: `read`, `write (docs/drafts)`
- **writes**: docs · **agent-run**
- **done**: a plan/doctrine doc concrete enough that another agent can build from it.

### `doc` — Documentation — keep live doctrine true, narrate history in the devlog.

- **tools**: `edit`, `/devlog`
- **writes**: docs · **agent-run**
- **done**: the doc reflects reality; narrative/history goes to a devlog entry, not doctrine.

### `security-remediation` — Close a remediation-queue row — a foreign CVE or an estate exposure.

- **tools**: `tools/rem-status.py`, `tools/discovery-scan.py`, `edit`, `pytest`
- **writes**: code · **agent-run**
- **done**: the queue row is resolved WITH resolved_by evidence AND the exposure is re-checked live — a pending row is not proof of exposure, and a closed row is not proof of a fix.

### `converge` — Apply committed SOURCE to the running estate (the repo is not the system).

- **tools**: `nos`, `ansible-playbook main.yml`, `tools/nos-smoke.py`
- **writes**: live · **operator-run**
- **done**: PLAY RECAP failed=0 AND nos-smoke passes; the change is now actually serving.

### `use-case` — A live use-case walkthrough / acceptance test of an end-to-end workflow, recorded with steps + expected + actual result.

- **tools**: `read`, `the running estate (UI, API, CLI)`, `edit`
- **writes**: docs · **agent-run**
- **done**: a recorded walkthrough with steps + expected + actual result, actual matching expected or a filed defect.
