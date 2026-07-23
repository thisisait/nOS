# 08 — "No containers" read as "nothing to wait for"

**Status:** OPEN. Found 2026-07-22 in the v0.9-beta release PR. Two defects,
one visible, one structural; neither is fixed yet.

## The fee

`files/anatomy/scripts/stack-health-probe.py` treats a stack with zero
containers as **ready**:

```python
# `docker compose up -d` (which blocks until containers are created),
# so an empty result here means the stack legitimately has none
# (e.g. every service in it is toggled off) — nothing to wait for.
print(f"{stack}: 0/0 ready (no containers — stack empty)")
```

The reasoning is sound and the premise is real: `up -d` does create containers
before returning, so an empty stack afterwards means every service in it was
toggled off. But the premise holds **only when `up` succeeded**. When it fails,
the same emptiness means the exact opposite — and the probe cannot tell the two
apart, because it never looks at whether `up` worked.

Observed on the Linux integration runner (CI 2026-07-22):

```
"infra: rc=1 open /home/runner/stacks/infra/docker-compose.yml: no such file or directory"
"infra: 0/0 ready (no containers — stack empty)"
```

`rc=1`. No compose file, therefore no MariaDB, no PostgreSQL, no Authentik, no
Traefik — the stack the architecture calls *"always required, always first"* —
and the **STRICT** health gate passed it. The run then provisioned for another
eight minutes on top of an estate with no infrastructure.

## What it cost, and why nobody was looking

`CLAUDE.md` says of this job:

> The Linux `integration-linux` job **is the gating wet-test** (green, full
> `ok=473` end-to-end run) — **it proves the playbook.**

It did not. It had been green with the infra stack never coming up. The only
check that noticed anything was the post-run smoke — and it was kept quiet by
its own tolerance: `nos_smoke_max_fail_ratio` defaults to `0.5`, so a handful of
dead probes stayed under the systemic-failure threshold. As services were added
over the following weeks the probe count grew, the ratio crossed 0.5, and the
gate finally went red — **not because the defect got worse, but because the
estate got bigger.**

So the fee compounded twice over: a gate that passes on absence, standing
downstream of a tolerance that hides the consequence until scale removes the
cover. Nothing failed. Nobody was looking. And a line in the project's own
constitution asserted the opposite of what was true.

## The rule

**Absence is only evidence of intent when the thing that creates presence
succeeded.** A probe that reads state without reading the outcome of the action
that produces it is measuring a different layer than the one that fails —
[`doctrine/gates.md`](../doctrine/gates.md).

Corollary, earned the same night: **a tolerance is not a gate.** A
majority-failure ratio protects against flaky probes, but it also silently
absorbs a systemic defect until the population grows past it. Any tolerance
that can hide a whole-stack outage needs a floor the outage cannot slip under —
e.g. *"a service the manifest says is enabled must answer, tolerance or not."*

## Paying it off

1. **The health probe must consult the bring-up result.** `stack-up`/`core-up`
   already register the `docker compose up` rc; a stack that reports zero
   containers after a non-zero `up` is a **FAIL**, and the message must say
   which one it is (`stack empty by configuration` vs `bring-up failed`). The
   probe currently cannot distinguish them and neither can the log reader.
2. **Fail the run at the failed `up`, not eight minutes later.** `infra` is the
   documented always-first invariant; every post-start task assumes it. The
   `rc=1` was printed and discarded.
3. **The Linux-side cause**: `stacks/infra/docker-compose.yml` is not rendered
   on Linux. Undiagnosed — do not guess. It is the reason the wet-test never
   tested what it claimed.
4. **Correct `CLAUDE.md`.** The sentence claiming this job proves the playbook
   must not survive unqualified while (1)–(3) are open.
5. **Smoke floor:** treat a manifest-enabled service that is DEAD as
   ratio-exempt, so one dead stack cannot hide under a tolerance sized for
   flaky probes.

Related: [`07`](07-messages-that-outlive-their-mode.md) is the same family from
the text side — this one is the machine saying "ready" about nothing at all.
