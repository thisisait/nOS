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
| [`roadmap.md`](../roadmap.md) | the prioritized forward plan |
| [`docs/llm/security/remediation-queue.json`](../llm/security/remediation-queue.json) | security findings, with severities |
| [`docs/doctrine/`](../doctrine/) | decisions already made and binding |

If a thing is failing, it is a bug — fix it or queue it. If it is planned work,
it is roadmap. This file is for the **third category**: known, not urgent, and
guaranteed to cost more the later it is found.

An entry graduating out of here is normal and good — it moves to the roadmap when
it becomes work, or gets closed by a gate that makes it fail loudly instead.

## Entry shape

One file per fee, `NN-short-slug.md`, with these headings:

- **The fee** — what is being deferred, in one paragraph.
- **When the bill comes due** — the specific future event that charges it.
  Vague ("eventually") means the entry is not understood yet.
- **How it was found** — usually "while looking at something else". Worth
  recording; it is evidence about where our blind spots are.
- **What closes it** — the gate, fix, or decision. Not necessarily scheduled.

## Index

| # | Fee | Bill comes due when | Status |
|---|---|---|---|
| [01](01-disabled-service-overrides.md) | A disabled service's compose override lingers on the host | a service is toggled off and its dead config keeps merging | open |
| [02](02-db-blind-healthchecks.md) | Healthchecks that answer without touching their database | a DB is reinitialised under a running container | partly closed |
| [03](03-leading-digit-slugs.md) | A service name starting with a digit cannot be a KEAP node id | someone adds a service whose name starts with a number | latent |
| [04](04-systems-docs-drift.md) | `docs/systems/` covers a third of the estate and targets dead paths | the skill router embeds them and starts routing | open |
| [05](05-keap-face-host-deprecation.md) | `KEAP_FACE_HOST` shim emitted for a pin we will leave behind | ~~`keap_repo_ref` moves past v1.21.0~~ | **closed 2026-07-21** |
