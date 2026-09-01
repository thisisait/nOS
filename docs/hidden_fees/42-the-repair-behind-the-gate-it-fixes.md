# 42 — The repair sat behind the gate it fixes

**Paid:** 2026-09-01, once, for sixteen minutes — and it would have been the
full 540-second budget and then a hard fail on a stack with a longer timeout.

**Found by:** changing one line of a config file. Not by a detector.

## What happened

Fee [40](40-config-rendered-and-never-read.md) closed the case of config
rendered into a running container that never re-reads it. The fix was
`tools/reload-stale-config.py`, run at the end of `main.yml`: after the stacks
are up, restart anything whose config is newer than its own `StartedAt`.

That placement is argued for in the task's own comment, and the argument is
good: on a blank run every container was just started with fresh config, so the
stale set is empty and there is nothing to do early.

It is also, it turns out, behind a gate that the very condition it repairs will
fail.

`wait-stacks-healthy` is STRICT by doctrine — every container must reach
healthy, no tolerance. Loki's healthcheck is:

    loki -target=all -config.file=/etc/loki/local-config.yaml -verify-config

So when a converge rewrote `local-config.yaml`, Loki did not degrade. It became
**unable to answer whether it was healthy**, the STRICT gate held at

    observability: 8/9 ready FAILED: loki-1[check cannot run — the image ships
    no such binary; the service may be fine]

…and the run never reached line 2386, where its own repair lived. The run that
caused the damage could not reach its own fix.

Two things in that message are worth pausing on. The probe guessed "the image
ships no such binary" — the binary was there; the *config* was gone. And "the
service may be fine" was true: Loki kept ingesting and answering queries the
whole time, on the config it had opened at start.

## Why rewriting a file removed it

MEASURED with a throwaway container, because the mechanism is not obvious and
guessing it wrong sends you to recreate containers you did not need to:

| what the host does | what the container sees |
|---|---|
| in-place write (`echo v2 > f.txt`) | `v2` — immediately |
| atomic rename (`echo v3 > .tmp; mv .tmp f.txt`) | **`No such file or directory`** |
| `docker restart` | `v3` |

A single-**file** bind mount binds the inode. Ansible's `template:` writes a
temp file and renames it into place, which puts a *new* inode at the path and
leaves the container holding the old, now-unlinked one. Not stale content —
ENOENT. A *directory* mount is unaffected, which is why this is invisible across
most of the estate.

`docker restart` is enough. `--force-recreate` is not needed, and reaching for
it would recreate containers on every config edit.

## What it cost, honestly

Sixteen minutes of one blocked converge, and no data loss: Loki never stopped
serving. The real cost is what the shape implies rather than what this instance
charged.

It had been latent for as long as the rendered content never actually changed.
Every converge re-rendered these files, every render reported `ok` because the
bytes matched, the mount stayed intact, and nothing was wrong. **The first
genuine content change in months is what surfaced it** — which means the fee was
sitting under every config-file edit anyone might make, waiting.

And the same converge left `observability-tempo-1` running with its config at
ENOENT for five hours without anyone noticing, because Tempo's healthcheck does
not read the file. The reader (`tools/stale-config-status.py`) named it; the
STRICT gate could not, because Tempo passes.

## What changed

The repair moved into `tasks/stacks/wait-stacks-healthy.yml`, before the poll
loop. One insertion point covers `core-up`, `stack-up` and `apps-up`, because
all three route through that file. It runs `failed_when: false` there — it is
the repair, and the poll loop immediately after is what judges whether it
worked. The end-of-run pass keeps the verdict, and still fails the play on
config a container never picked up.

- Gate: `tests/anatomy/test_the_repair_runs_before_the_health_gate.py`, verified
  red against all four ways this regresses (repair removed, repair after the
  poll, repair judging, end-of-run pass going lax).
- Doctrine: `docs/doctrine/foreign-properties.md` §8 — the inode fact is
  Docker's, not ours.

## What is still owed

**The generalisation has no gate.** "A step that repairs a condition must not
sit behind the gate that condition fails" is now true in this one file. Nothing
looks for the next instance of it.

**The health probe misreports why a check failed.** "the image ships no such
binary" was a guess presented as a finding, and it sent the first ten minutes of
diagnosis at the wrong thing. A check that fails should say what the exit code
and output were, not infer a cause.

**`iiab-apex-1` has been serving replaced config for 356 hours** and is excluded
from repair by its own `reload: {mode: self}` manifest opt-out. That opt-out is
a claim that the service re-reads on its own. Nothing verifies it.
