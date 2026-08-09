# 02 — cortex-lang: an ontology-typed pipeline IR

**Status: design frozen (P0 spec, freeze-ready after two review rounds). The
Wing executor now EXISTS (`files/anatomy/wing/app/Cortex/`, 2026-08-09) and
executes two of its seven verbs; the other five wait on KEAP routes that are
not published yet — see [What is actually built](#what-is-actually-built).**
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
| **Wing executor** | **present, and refuses five of its seven verbs** |

The executor is the capability boundary — three-axis scoped tokens
(`verbs`/`namespaces`/`tenants`). `files/anatomy/wing/app/Cortex/` landed on
2026-08-09 (`901ec719`): registry, capability, binding gate and seven handlers,
of which `get` and `resolve` execute and the other five extend
`LateBoundHandler`. That is not modesty about untested code — it is a
**measurement about the other side**: KEAP publishes no taxonomy/search/
classify/embed route to any bearer Wing holds, so those five verbs have nothing
to bind to yet.

Until they bind, [06](06-genome.md)'s hydrator still has nowhere to land for
anything but `get`/`resolve`.

## Next

Two of seven verbs execute. The next move is on the KEAP side — publish the
routes the remaining five late-bind against — not on Wing's, where the handlers
are already waiting for them.
