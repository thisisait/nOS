<!-- GENERATED from state/task-types.yml by tools/task-types-render.py — do not edit by hand. -->
# AGENTS.md — the task-type router

Every row on the board carries a **`task_type`**. A row is a *claim*; its
task_type is the tiny contract for HOW to work it. Read your row's type below,
reach for its tools, and end it with its evidence — nothing more.

This is the router. The full estate reference is [CLAUDE.md](CLAUDE.md); the
machine-readable source of this table is
[`state/task-types.yml`](state/task-types.yml). Adding or changing a type is a
**proposal** through the loop, not a free edit.

## Three invariants that outrank every task type

1. **Success is written by a READER, not by the thing that attempted the work.**
   A backup that reports its own success, a gate you can pass by editing the
   gate, a queue row that marks itself done — all lie. Prove it from the outside.
2. **Run the gate against the BROKEN state too.** A check that cannot fail on the
   pre-fix tree pins nothing.
3. **The repo is not the running system.** Source lives here; the estate runs
   from elsewhere and converges only on an operator's `nos`. A git ref answers
   "what is in the repo", never "what is running".

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

- **tools**: `read`, `write (docs/plans, docs/doctrine)`
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
