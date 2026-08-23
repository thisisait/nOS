# Hidden fees

**Costs already incurred, not yet billed.**

A hidden fee is a decision that works today and charges you later: a mechanism
that fails silently, a shortcut that only hurts at scale, a value that is correct
until an unrelated thing changes. They are not bugs — a bug fails and you fix it.
A hidden fee *passes*, and then one day the bill arrives somewhere far from where
the decision was made.

The defining property, and the entry test: **nothing is failing, and nobody is
looking.** Almost every entry here was found sideways — while investigating
something else — because there is no signal that finds them on purpose.

## What belongs here

- A guard that can report success without having actually checked.
- A value that is right now and silently wrong after some future change
  (a version bump, a rename, a service being added).
- Something create-only where the world expects reconciliation.
- A cost that is invisible at today's size and structural at tomorrow's.
- A workaround that got spelled around once and will not be next time.

## What does NOT belong here

| Surface | Holds |
|---|---|
| [`active-work.md`](../active-work.md) | what to do **now** |
| the `nOS Roadmap` table | the prioritized forward plan — ask it with `tools/roadmap-status.py`; [`roadmap.md`](../roadmap.md) is the pointer and the v1.0 exit criteria |
| [`docs/llm/security/remediation-queue.json`](../llm/security/remediation-queue.json) | security findings, with severities |
| [`docs/doctrine/`](../doctrine/) | decisions already made and binding |

If a thing is failing, it is a bug — fix it or queue it. If it is planned work,
it is roadmap. This file is for the **third category**: known, not urgent, and
guaranteed to cost more the later it is found.

An entry graduating out of here is normal and good — it moves to the roadmap when
it becomes work, or gets closed by a gate that makes it fail loudly instead.

## Entry shape

One file per fee, `NN-short-slug.md`. Four things have to be in it; since
entry 18 they are section titles written for the specific fee rather than a
fixed set of headings, because the interesting part of a fee is usually the
mechanism and a fixed form kept burying it under boilerplate:

- **The fee** — what is being deferred, in one paragraph.
- **When the bill comes due** — the specific future event that charges it.
  Vague ("eventually") means the entry is not understood yet.
- **How it was found** — usually "while looking at something else". Worth
  recording; it is evidence about where our blind spots are.
- **What closes it** — the gate, fix, or decision. Not necessarily scheduled.
  Entries that close only part of a fee say which part, and keep
  `## What is still owed`.

## Index

| # | Fee | Bill comes due when | Status |
|---|---|---|---|
| [01](01-disabled-service-overrides.md) | A disabled service's compose override lingers on the host | ~~a service is toggled off and its dead config keeps merging~~ | **override half closed** (prune-disabled.yml); other resources open |
| [02](02-db-blind-healthchecks.md) | Healthchecks that answer without touching their database | a DB is reinitialised under a running container | **4 of 6 verified 2026-08-18**; hedgedoc fixed, superset is the open instance |
| [03](03-leading-digit-slugs.md) | A service name starting with a digit cannot be a KEAP node id | ~~someone adds a service whose name starts with a number~~ | **closed 2026-07-26** |
| [04](04-systems-docs-drift.md) | `docs/systems/` covers a third of the estate and targets dead paths | the skill router embeds them and starts routing | open |
| [05](05-keap-face-host-deprecation.md) | `KEAP_FACE_HOST` shim emitted for a pin we will leave behind | ~~`keap_repo_ref` moves past v1.21.0~~ | **closed 2026-07-21** |
| [06](06-removal-guard-drifts-from-deploy-gate.md) | Removal answered a question the deploy had stopped asking | ~~the write-gate and the remove-gate diverge~~ | **closed 2026-07-22** |
| [07](07-messages-that-outlive-their-mode.md) | Operator-facing text that outlived the mode it was written for | a flag changes and the sentence does not | open (4 paid) |
| [08](08-empty-stack-reads-as-success.md) | "No containers" read as "nothing to wait for" | a `compose up` fails and the health gate passes the emptiness | open |
| [09](09-untuned-vector-index.md) | The vector index is 8× larger than it needs to be | being paid now — 449 MB and an 8× slower embed pass | open |
| [10](10-cortex-organ-cannot-recall.md) | The cortex organ can typecheck but cannot remember | anything is built assuming the organ is where reasoning happens | open |
| [11](11-vendored-cortex-copies-drift.md) | Two implementations of one language, nothing compares them | ~~a KEAP change lands without a re-vendor~~ — **it already has** | **comparator paid 2026-08-18** (14 undeclared drifts); S5 open |
| [12](12-keap-image-tag-is-not-a-version.md) | `nos/keap:<version>` means "whatever the last build produced" | ~~a rollback is attempted~~ · a hand-pull mid-run | **tag paid 2026-08-18**; ingest handshake open |
| [13](13-per-user-db-without-enforcement.md) | A per-user database chosen by an unauthenticated parameter | the first user who must not read another's data | open |
| [14](14-a-long-run-cut-from-under.md) | A long run's paths change under it mid-flight | the next multi-hour run that outlives the tree it started in | open |
| [15](15-a-lineage-that-does-not-join.md) | The loop records a lineage whose first link does not join | ~~the first real autonomous run~~ | **write half paid 2026-08-16**; read half open |
| [16](16-an-agent-is-five-declarations-nothing-names.md) | Onboarding an agent is five declarations and nothing names the set | the next agent, at runtime, as one symptom naming one layer | **gate paid 2026-08-18** (found curator); one-source open |
| [17](17-php-tree-never-audited.md) | Wing's own dependency tree has never been audited | any CVE in it that matters more than a URL parser | open (1 paid) |
| [18](18-a-report-that-reaches-nobody.md) | Four agents wrote reports the operator inbox never received | ~~the first night an agent finds something that matters~~ | **closed 2026-08-22** (gate + WARN on a non-200) |
| [19](19-a-repair-the-reader-cannot-see.md) | A repair applied by hand is indistinguishable from drift | the next reader who trusts the queue over the estate | **gate paid 2026-08-22**; reconciliation open |
| [20](20-a-third-of-the-queue-is-closed-on-its-word.md) | 50 of 165 closed findings carry no evidence at all | an audit, or the first re-opened row | **ratchet paid 2026-08-22**; 50 rows open |
| [21](21-the-earliest-consumer-was-named-not-derived.md) | The earliest eager consumer of `{{ vars }}` was named, not derived | ~~the first full converge after a var moves~~ | **both halves paid 2026-08-22**; wholesale `{{ vars }}` open |
| [22](22-a-probe-that-could-never-pass.md) | A roadmap probe that counts prose can never reach the state its row waits for | being paid now — `sec-rem` read `contradicted` from the day it was filed | **closed 2026-08-23** (probe + gate); decisiveness unguardable |
| [23](23-a-pin-that-never-rendered.md) | A client TLS pin that resolved a role default out of scope, and rendered plaintext for nine weeks | ~~measured, 2026-08-22: the vault talking to its store in clear~~ | **fixed + 2 gates 2026-08-23**; live effect unverified until a converge |
