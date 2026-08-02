# 14 — A long run cut from under itself

**Status:** OPEN as a class; the primitive exists (`tools/worktree-lease.py`),
the enforcement is advisory. Found 2026-08-02, by causing it.

## The fee

A workflow was mid-run in a worktree — nine agents spawned, two still in flight —
when the main session moved `plugins/nos-loop` to `.claude/plugins/nos-loop`.

Nothing was corrupted. That is what makes it a fee rather than a bug: the tree
was consistent, every test passed, and the cost was paid somewhere nobody was
looking. Every in-flight agent still held the old path. The next one to read it
would have reported *"the plugin does not exist"* — **a finding manufactured by
the session that would then have to triage it.**

The move itself was correct: a top-level `plugins/` collided with
`files/anatomy/plugins/` (72 anatomy plugins, a different meaning) and had
already broken an unrelated gate, because `docs/systems/jellyfin/README.md`
cites `plugins/configurations/SSO-Auth.xml` — a path *inside the Jellyfin
container* — which a new top-level directory turned into a repo-relative claim.

**A correct change at the wrong moment is still a fee.** Nothing was burning.
The gate was red and would have stayed red for another twenty minutes.

## Why the existing answer did not cover it

`files/anatomy/scripts/pulse-run-agent.sh` already solved a neighbouring problem
in 2026-05-27: claude-CLI agents fired concurrently killed all participants, so
it takes an atomic `mkdir` lock with a PID-liveness reclaim. Good machinery —
and the wrong shape here. That is a **mutex**: one at a time. A workflow
legitimately runs a dozen subagents in one worktree, and serialising them defeats
the workflow.

The lesson was learnt once, for one call site, and never generalised. That is the
recurring shape in this ledger: a fix that fits the incident and not the class.

## The rule

> **While a lease is held, PATHS ARE IMMUTABLE. Content may change; shape may
> not. Adding a path is always allowed; moving or deleting one is not.**

The asymmetry is the insight, and it is not arbitrary: **nothing can hold a
stale reference to a path that did not exist yet.** Creation cannot invalidate an
in-flight reader. Relocation always can.

That makes the rule narrow enough to actually be obeyed. "Do not touch the tree
while agents run" would be ignored within a day, because the main session has
legitimate work — writing new files, editing content, committing. Only the shape
is off limits.

## The primitive

`tools/worktree-lease.py acquire|check|release|status`

- atomic `mkdir`, because macOS has no `flock` — the same trick the pulse mutex
  uses, borrowed deliberately rather than reinvented
- liveness is **observed** (`kill(0)`), never self-reported: a holder that wrote
  "done" and then died would be believed by a status field and is not believed by
  a signal — fee 07's rule, applied to a lock
- a TTL as a backstop for a recycled pid
- `rmdir` + `unlink`, never `rmtree`: a misset path must not widen the blast
  radius (also borrowed from the pulse mutex)
- the lease lives in `~/.nos/`, keyed by absolute worktree path — runtime state,
  not repo state. A lease file inside the tree would be a path the lease forbids
  moving.

## What is still unpaid

**It is advisory.** It cannot stop a process that does not ask, and the process
that most needed to ask on 2026-08-02 was the one holding the keyboard. The
enforcement half — the workflow runner taking a lease for its own duration, and
the session consulting it before a structural change — is not built.

Until it is, this entry is the mechanism *and* the reminder that the mechanism is
not yet wired to anything that must obey it.

Related: [`07`](07-messages-that-outlive-their-mode.md) — a record that outlives
the situation it described. A path assumption is exactly that, held in an agent's
context instead of a log line.
