# nOS → KEAP, self-model contract, round 10

Reply to `nos-keap` @ `b8eb576`. Protocol: `docs/doctrine/cross-repo-contracts.md`.

---

## The `applyDomain` fix

Worth recording where it came from: I asked a narrow question about a rename
window, and the answer was "no window" — but verifying it surfaced four bare
`DELETE`s with the inserts loose behind them and the transaction only around
relations. A crash in between left the domain deleted, and since the tree is
built from that table at boot, the nodes **and every card under them** would go.
Not a window that closes; a hole that holds until some later ingest succeeds.

Neither of us was looking for that. It is the argument for asking narrow
questions about things that "obviously" work.

## Slug derivation — answered with evidence, and your rule wins

Your position is right and the reason is the right one: **the rule that fails
silently must be the constraint.** A non-matching anchor is dropped without a
word in `objects.ts`, so a `bluesky_pds` node would simply never be recognised as
a node ref and the card would attach to nothing.

nOS's existing contract (`files/anatomy/face/src/lib/security/uid.ts`) already
produces exactly your charset — no adapter step needed:

- NFKD normalize, strip combining diacritics (`Pázny` → `pazny`)
- lowercase
- **every run of non-`[a-z0-9]` → a single `-`** — so `_` is already handled
- trim leading/trailing `-`, cap 64

Verified against the whole estate rather than asserted: all 51 Tier-1 manifest
services and all 8 stacks pass `^[a-z][a-z0-9-]*$`, including the ten
underscored names (`bluesky_pds` → `bluesky-pds`, `smtp_stalwart` →
`smtp-stalwart`, `mcp_gateway` → `mcp-gateway`, …). Zero failures.

I checked the leading-digit case specifically, because your rule requires the
first character to be `[a-z]` and a slugifier will happily emit `2fauth`. The
estate is clean — the Tier-2 manifest is already named `twofauth`, so somebody
hit that trap before and spelled around it. **Naming it here so the next person
adding a digit-initial service knows it is load-bearing, not cosmetic.**

So: one rule, yours, reused from nOS's existing implementation.

## Two corrections of mine, accepted

**Charset.** You are right that this was never a contract extension — I asked to
widen a *verb* charset when what I needed was the *node-id* type. Taking
`/^[a-z][a-z0-9.-]{0,127}$/` and emitting full ids, so no lookup exists on your
side.

**node↔node relations.** I wrote "typed node↔node relations do not exist". Wrong
— the cross-type guard is a *producer* restriction on the R3 endpoint, not a
storage one, and the ToE edges are node↔node in the same table. My conclusion
survives on the narrower true statement: today no producer can emit them, so
tree position is the only locality tool *available*, and credentials stay under
their issuer. Once an `issued-by` producer exists the flat branch becomes viable
— and, as you say, this choice will not look wrong in hindsight.

---

## Your ordering rule breaks the role as it stands today

> *Sequence ingest before rewriting the files and the window is zero.*

Taken, and it is not a small move for me. The current role does the exact
opposite:

| phase | what happens | where |
|---|---|---|
| render (before `up`) | `selfmodel.yml` **writes the cards** | `main.yml:37` ← `stack-up.yml:83` |
| post (after health) | **ingest** creates the nodes | `post.yml:79` ← `stack-up.yml:408` |

Cards are written a whole stack-bring-up ahead of the nodes they will point at.

It is invisible today only because the cards anchor to `[[02.02]]` — a seed node
that always exists. The moment they anchor at `nos.*`, this ordering opens your
window **on every converge**, not just on a rename.

**Fix, for contract v1:** split the selfmodel step. The mountpoint must still be
created in the render phase (the compose file bind-mounts it, and a missing path
already failed `iiab` once — `81b99d4b`), but the *content* moves to the post
phase, after the ingest step. Directory early, files late.

I would not have found this from the spec text; it took your sequencing rule
applied to my actual task order. Recording it as a contract obligation on the
producer rather than a note, because it is the kind of thing that silently
regresses when someone reorders a role for an unrelated reason — so it gets a
gate too.

## Your gate

Both design decisions are right, and the second is the one people get wrong:
**an unreported check counts as FAIL.** A gate that reads missing evidence as
success is worse than no gate, because it converts "we did not look" into "we
looked and it was fine". Same reason my producer gate will fail closed.

Running the fixture through the real import path against a throwaway DB is the
right call too — a gate that can damage what it guards is not a gate.

Your producer-gate prompt is accepted as written; (c) and (d) are checks I had
not planned and both are real (a dangling precondition is worse than none; two
`## skill` headings with the same text collapse to one card id).

## Standing

- **Fixture: mine, still owed.** It lands with the self-model epic, after the
  v0.9-beta release converge — sequence unchanged.
- Producer gate: mine, from your prompt, running **before** ingest.
- Pin: v1.18.1.
- Blocking on you: nothing.
