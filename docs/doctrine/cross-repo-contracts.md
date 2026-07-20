# Cross-repo contracts — how nOS and a sibling repo agree on a shared surface

nOS produces surfaces that another repo consumes (today: the KEAP self-model —
nOS emits a knowledge tree, KEAP ingests and renders it). Each repo has its own
release train, its own agent, and its own opinion. This file is the protocol for
keeping them honest with each other.

**Why this exists:** the self-model drifted for months. nOS emitted nine files
named `_stack.md` carrying one near-identical sentence; KEAP embedded them into
nine nearly-identical vectors that became top recall hits for unrelated physics
queries. Neither side was wrong about its own half — there was no shared
artefact that could fail. Prose agreement is not a contract; **a contract is
something that can go red.**

## The three artefacts

1. **The spec** — one document, one physical location, cited by both repos
   (never forked into a local copy — two copies diverge, and then the contract
   is whichever copy you happened to read). Carries `contract_version: N`.
2. **The fixture** — a small, committed, representative sample of the surface,
   owned by the PRODUCING side. Not a description of the shape: the shape
   itself.
3. **Symmetric gates** — the producer asserts *"I still emit this fixture"*; the
   consumer asserts *"ingesting this fixture yields what I promised"*. Both run
   in their own CI, against the same bytes.

Symmetry is the whole design. A gate on one side only makes that side the
authority and the other side the supplicant; then drift is discovered by a human
noticing something looks wrong on a live map, which is exactly what happened.

## Peer rules

- **No hierarchy.** Neither agent assigns work to the other. Each states what it
  needs, what it will provide, and what it refuses — and expects to be argued
  with. "The other side asked for it" is not a reason to build something.
- **Objections are first-class.** Either side may object to any clause. An
  objection is a claim plus its evidence (file:line, a measurement, a failing
  case), and it **blocks the version bump until answered on the merits** —
  answered, not overruled.
- **Neither side edits the other's half.** The producer does not rewrite the
  consumer's assertions to make its gate pass, and vice versa. Fix the surface
  or renegotiate the clause.
- **Disagreement is the point.** The two agents see different failure modes:
  the producer knows what its generator can guarantee, the consumer knows what
  its ingest actually does with it. A contract both sides agree to instantly is
  usually one neither side has tested.

## Changing the contract

1. Raise it as an objection or a proposal, with evidence, in the spec's open
   items.
2. The other side answers on the merits.
3. On agreement: bump `contract_version`, update **both** gates and the fixture
   **in the same change**. A version bump with one gate updated is the failure
   this protocol exists to prevent.
4. Record the decision and the reasoning — including what was rejected and why.
   The next agent inherits the conclusion but not the argument, unless it is
   written down.

## Invariants a contract must carry

Every shared surface pins at least: **identity** (what makes a thing the same
thing across a re-emit — a stable key, not a hash of something incidental),
**visibility** (a produced item that silently fails to render is worse than one
that errors), and **removal** (what the consumer does when the producer stops
emitting something).

Those three are where drift hides, because none of them fails loudly on its own.

## Live contracts

| Surface | Spec | Producer | Consumer |
|---|---|---|---|
| nOS self-model → knowledge tree | `nos-keap:docs/specs/nos-selfmodel-keap-contract.md` | nOS (`files/anatomy/scripts/keap_selfmodel_gen.py`) | KEAP (`server/fs-sync.ts`, `knowledge/ingest.mjs`) |
