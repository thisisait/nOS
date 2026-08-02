# 02 — cortex-lang: an ontology-typed pipeline IR

**Status: design frozen (P0 spec, freeze-ready after two review rounds). The
Wing executor is designed and NOT built — `files/anatomy/wing/app/Cortex/` does
not exist.**
**Detail:** [`nos-cortex-lang.md`](../archive/nos-cortex-lang.md) ·
[`nos-cortex-lang-wing-executor.md`](../archive/nos-cortex-lang-wing-executor.md)

## The idea

An LLM emits a **typed plan** against a known ontology. The plan is validated,
then executed **locally**. The model never executes anything, and:

> **A capability may never be added by data.** Facts about an entity are data,
> declared once and inherited. What may *act* on an entity is code, per runtime,
> hash-compared — never addable by declaring it.

That single rule is what separates this from "let the model write SQL".

## External evidence the shape is right

WrenAI (audited 2026-08-02, `technosideas/wrenai.md`) independently converged on
three of the same decisions: the zero-side-effect validate/execute split, a
compiled-and-hashed contract artifact, and a confirmed-pair corpus stored as
files with a derived, rebuildable index.

**Nothing is importable.** Their LLM still emits free-form SQL and their
validator is sqlglot/DataFusion-bound. The value is the confirmation.

## The lesson to NOT copy, which is sharper than the confirmation

WrenAI's headline repair affordance: a failed validation returns **the available
columns**. That is an enumeration oracle — already forbidden by the round-2
review. They can afford it (single-tenant, no user model at all in OSS); nOS
cannot.

**The most attractive-looking feature is the one to reject**, and it is worth
carrying that as a design guard rather than a footnote.

Their issue #2409 is the argument *for* a closed vocabulary: `read_csv(/etc/passwd)`
blocked in `FROM` but allowed in a projection, closed with a maintained
**denylist** rather than fail-closed. That is the standing cost of a free-form
expression language.

## What is actually built

| piece | state |
|---|---|
| `POST /agent/v1/validate` in KEAP | live |
| opcode registry + hash compare | live (Wing refuses to boot on a published opcode with no handler) |
| `onto1:` ontology hash gate | live, pinned |
| **Wing executor** | **designed, absent** |

The executor is the capability boundary — three-axis scoped tokens
(`verbs`/`namespaces`/`tenants`). Until it exists, [06](06-genome.md)'s hydrator
has nowhere to land, and an external system has no way to satisfy a contract at
runtime.

## Next

Build the executor read-only first (P1 is explicitly read-only by design), then
weigh whether the hydrator is a second consumer or the first real one.
