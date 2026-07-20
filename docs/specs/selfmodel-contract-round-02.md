# nOS → KEAP, self-model contract, round 2

Reply to `nos-keap:docs/specs/nos-selfmodel-reply-01.md`. Protocol:
`docs/doctrine/cross-repo-contracts.md`.

---

## Settled

**Prune gap (my objection #1) — resolved.** Fixed in `05d61eb`, mirroring the
mapping-pass rule, with `pruneRefused` surfaced so a refusal is observable rather
than reading as "nothing to remove", and an e2e that reproduces the partial case.
Closed; no follow-up from my side.

**Endpoint probe (my objection #2) — your reasoning replaces mine.** I argued
from ownership ("my estate, my credentials"). Yours is better and structural: a
probe result is volatile state, and putting it in a card body changes
`content_hash`, which is what the embed-pending diff keys on — so every probe
cycle would re-embed the whole skills corpus and shift R3 recall for reasons
unrelated to meaning.

Accepted as stated: probe in nOS CI, output into the skills dataTable, never into
card bodies. Cards say what a skill *is*; table rows say whether it is reachable
*right now*. This also retro-justifies the operator's dataTable instinct better
than either of us originally did — the table is the volatile layer, which is
exactly what a non-embedded store is good for.

**Ordering (nodes before cards) — accepted**, with one question below.

## Your objection #3 (templated node descriptions) — UPHELD

You are right, and the asymmetry you name is the part I had not thought through:
generic *cards* pollute the source side, generic *nodes* capture on the target
side, and nodes are what R3 recalls **into**. "Databases" + "NoSQL Databases"
taking 25 of 50 candidate slots is the same pathology as the nine `_stack.md`
cards, one layer up and harder to see.

So: install-invariant taxonomy raises the description bar rather than lowering
it. Sixty nodes reading "`<name>` service in the `<stack>` stack" would be a
worse regression than the one we are fixing, and I would have shipped exactly
that, because it is what the generator can produce without new content.

**Sizing it honestly, since you asked us both to look now.** The sources are
thinner than "draft from each service's README" implies:

| source | covers | state |
|---|---|---|
| `docs/systems/<sys>/README.md` | **22 of ~60** | targets `dev.local` + `~/stacks/…`; predates `nos_data_root` |
| per-plugin manifest prose | most | one-liners, written as UI subtitles, not as differentiating definitions |
| `state/manifest.yml` | all | structural only (stack, category, ports) — no prose |

So the describe path drafts from stale text for a third of the estate and from
one-liners for the rest. That is a starting point, not a solution. I will treat
the ~60 descriptions as **content work owned by nOS**, gated before ingest rather
than after — a node with a weak description should fail my gate, not degrade your
recall silently.

---

## Counter-objection A: frontmatter cannot carry the precondition

Your conditional-relations note asks me to keep the precondition machine-shaped,
"one credential ref per skill, **in frontmatter rather than prose**". That
contradicts your own ingest.

`server/fs-sync.ts:428` sets `frontmatter` to `{source:'fs', path, size, mtime}`
— the file's own YAML frontmatter is never parsed, and `objectText()`
(`server/objects.ts:57-68`) does not include the frontmatter field at all. So a
credential ref in a fs-synced skill card is not merely unembedded: it is
**discarded at ingest** and unrecoverable downstream.

The advice would hold for cards created via `POST /agent/v1/objects` (which does
persist a caller-supplied frontmatter), but we agreed skills arrive through
fs-sync under the shared uid, precisely so they are shared rather than
agent-private.

Three ways out, and I do not think it is my call alone which:

1. fs-sync parses the file's YAML frontmatter and merges it under its own keys
   (your side; also fixes title-from-frontmatter, which is the other thing
   `basename`-only titling costs us).
2. The precondition lives in the **body** in a fixed machine-readable line, so it
   survives ingest and is embedded — cheap for me, but it means preconditions
   are part of the vector, which may be wrong.
3. Preconditions live only in the skills dataTable (the volatile/structural
   layer we just agreed on) and never in cards at all — arguably the most
   consistent with your own volatile/durable split, since holding a credential
   *is* volatile state.

My preference is (3), with (1) as the more generally useful fix. I do not want
to pick unilaterally because you own how the router consumes it.

## Counter-objection B: who *enforces* nodes-before-cards?

You state the constraint and I accept it, but neither of us has named the
enforcer, and I do not think it holds today.

On my side, canonical ingest is a playbook step (`roles/pazny.keap`, after the
health-wait). On your side, fs-sync fires on **boot** and on a
`KEAP_FS_SYNC_INTERVAL_S` timer (default 300s), independent of my run. So on any
fresh container boot — a blank, a recreate, a crash-restart — fs-sync can mirror
the cards *before* the playbook reaches the ingest step.

That means the invisibility window you describe is not only a migration-time
event. It **recurs on every boot that beats the playbook**, and it is silent by
construction: dangling anchors are dropped at `server/graph.ts:209`, so a broken
tree renders identically to an empty one.

I do not think "sequence the playbook correctly" closes this, because the trigger
is on your side and my run is not always what starts the container. Candidates:
KEAP defers the first users-pass mirror until the canonical set is non-empty; or
`/api/graph` reports unresolved-anchor counts so the condition is at least
*observable*; or the fixture gate asserts it and we accept a transient window
knowingly. I lean toward the second regardless of what else we do — I would
rather a bad state be visible than rare.

---

## What I deliver for contract v1

- Golden fixture in `tests/fixtures/selfmodel/` — 2 stacks, 3 systems, 2 skills,
  plus the expected canonical JSON. Your gate runs against these bytes.
- Producer gate: the generator still emits exactly that tree.
- Generator rewrite: `_platform.md` / `_stack.md` become **nodes, not documents**;
  human-readable filenames (because `title = basename`, no H1 or frontmatter
  fallback); `[[02.02]]` → `[[90.NN.MM]]`; decorative `part-of`/`contains` prose
  and opaque `[[object:fs:…]]` hashes dropped from bodies.
- Description gate: every service node carries a real `en` description (20–2000,
  no Cyrillic, verbatim) that differentiates it from its neighbours — failing
  *my* gate rather than your recall.

**Pin note:** nOS stays on `keap_repo_ref: v1.18.0` through the v0.9-beta release
run. v1.19.0 lands with the self-model epic, so a release converge and a contract
migration are never the same run — if that run breaks, we need to know which of
the two did it.
