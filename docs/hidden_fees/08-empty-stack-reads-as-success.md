# 08 — "No containers" read as "nothing to wait for"

**Status:** OPEN in part. Found 2026-07-22 in the v0.9-beta release PR. Three
of the five payoff items below were paid 2026-08-26 and re-verified against
the artifacts 2026-08-27: the probe now carries a denominator
(`_expected_service_count`, gate `test_stack_health_probe_absence_has_denominator.py`),
`core-up.yml` fails fast on a non-zero `up` (gate
`test_core_up_fails_fast_on_bring_up.py`), and the CLAUDE.md claim is
qualified. **Items 3 (Linux `infra` non-render) and 5 (smoke fail-ratio floor,
not built) remain open.**

**ITEM 3 RE-MEASURED 2026-08-27, on the first Linux wet-test to get past
preflight in four weeks** (PR #27; the run had been aborting at the P0 password
guard since 2026-08-02, and `integration-linux` is skipped on pushes to `dev`,
so nothing surfaced it). What the log shows:

  * `iiab: 3/3 ready` and `apps: 5/5 ready` — real containers, health-waited.
  * **Zero** occurrences of `0/0 ready`, `bring-up produced no containers`, or
    `expected service count UNKNOWN` anywhere in the run.
  * ok=537 changed=139 unreachable=0; the only failure is `nos-smoke.py`, where
    7 of 9 targets are `*.dev.local` URLs a runner cannot resolve.

So the symptom this item was written from — an empty `infra` passed as ready —
did NOT occur. But the run contains **no health-wait line for `infra` or
`observability` at all**, so their readiness is not positively demonstrated
either. That is UNKNOWN, not fixed: the item stays open until a Linux run shows
those two stacks' own ratios.

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

---

## Update 2026-08-02 (v0.10-beta release PR) — the fee is now VISIBLE, still unpaid

Still **OPEN**, but the shape has changed and item (3) is no longer where the
run stops. The job had not executed since `pazny.cortex` was Ansible-ized, and
on the release PR it ran four times, each surfacing one real defect:

1. `ok=226` — the cortex mount sentinel hard-failed on any absent
   `nos_data_root`, conflating "removable volume not mounted" with "ordinary
   directory nobody created". Fixed + gated
   (`test_data_root_absent_means_two_things.py`).
2. `pazny.backup` — an **ungated brew call does not skip on Linux**; Linuxbrew
   is on `$PATH` and ran the formula. Six instances, fixed + gated
   (`test_brew_calls_are_platform_gated.py`).
3. `pazny.backup` again — the apt branch written for (2) guessed a package that
   Ubuntu dropped after 22.04. Replaced with the vendor installer.
4. **`ok=550 changed=141 failed=1`** — the playbook now runs END TO END and
   fails at the smoke gate: `Infra: FAILED`, apps stack-up `rc != 0`,
   **1 / 8 probes OK**.

So the wet-test no longer passes an empty estate; it completes the playbook and
**reports that the estate is not serving**. That is this fee being charged out
loud for the first time.

One claim in this document is now too strong and is withdrawn: *"it is the
reason the wet-test never tested what it claimed."* It tested very little
because the run died early, not only because of the probe's tolerance. Getting
226 → 550 tasks turned it into an instrument that finds real defects. The probe
weakness (items 1, 2, 5) is unchanged and still needs paying.

---

## The probe half, paid — and a fan-out with three of four answers discarded

**2026-08-29.** The probe weakness above is closed. Zero containers is no longer
one case: `stack-health-probe.py` derives the EXPECTED service count from the
rendered compose inputs, so `0/0 ready (stack empty by configuration)` is now a
claim with evidence behind it, `0/? ready (expected service count UNKNOWN)` is
what it says when it cannot tell, and UNKNOWN is never folded into ALL_READY —
the health-wait keeps polling and then fails loudly. `core-up.yml` stops the run
on a non-zero `docker compose up -d` instead of registering the rc, printing it
and discarding it. Gates:
`test_stack_health_probe_absence_has_denominator.py`,
`test_core_up_fails_fast_on_bring_up.py`.

**How it was built, which is the part worth recording.** Four agents worked the
same fee in parallel worktrees. Two produced what landed. One left a dirty tree
and no commit. The fourth produced a complete, well-argued alternative: the
caller passes its `up` rc to the probe through `NOS_STACK_UP_RC`, and a stack
missing from that map reads UNKNOWN. It was **rejected on doctrine, not on
quality** — it asks the code that attempted the bring-up to certify the
bring-up, and this estate has paid repeatedly for success markers written by the
attempting code (`dispatched_at` stamped by the sender; `status=scanned` stamped
by a scan that never ran). Counting the services the compose file declares reads
an artifact instead. Kept as `archive/wf-de1-4-up-rc` so the reasoning survives
the branch.

Three of four answers discarded is not waste — it is what a fan-out is for. What
would have been waste is leaving them in worktrees for a month, where the next
reader finds four unmerged attempts and cannot tell landed from rejected from
abandoned.

**Still open**, and the reason this fee is not closed: the Linux wet-test
completing end-to-end is not the same as the Linux estate serving. That is
`plat-linux`, and it is blocked on the estate, not on the probe.

---

## Closed

**2026-09-03, run 33734196338.** The Linux wet-test is green and the green is
earned: full playbook `ok=669 failed=0`, main smoke **11/11 OK** (Authentik 200,
every forward-auth route answering its 302, wing host daemon under
`systemd --user`, bone, traefik), Tier-2 smoke **4/4 OK**. Four layers stood
between the old false green and this one, each hidden under the previous:
no edge at all (46 days) → `install_authentik: false` against 7 gated routes →
the blueprint apply failing on a SEC-1 0600 bind since 2026-05-23 (`|| true`
swallowed it; macOS VirtioFS masked it) → the smoke's loopback retry chasing a
working outpost's absolute redirect to a name only the estate resolves. The
last two were estate defects the wet-test caught — which is the whole argument
for having one.
