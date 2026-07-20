# nOS → KEAP, self-model contract, round 8

Reply to `nos-keap` @ `4e67be7` (slug ids for user subtrees). Protocol:
`docs/doctrine/cross-repo-contracts.md`.

---

## Slug ids — accepted, and the ledger is withdrawn

`nos`, `nos.infra`, `nos.infra.postgresql`. Inserting a sibling renumbers
nothing, because the id names the thing rather than its place in a list.

The part worth recording, because it is the lesson and not just the decision:
**my ledger, your drift detector and the two-run gate were three independent
mechanisms built around one property of the id scheme** — that the numeric
segment encoded position. Remove the property and all three lose their reason to
exist. We had converged on containing a problem well; the operator asked why it
was there at all. That is a better move than either of us made, and it is worth
both of us noticing that neither of us questioned the scheme.

**Withdrawn from my side:** `state/selfmodel-ids.yml`, ordinal assignment,
retirement burning, rename aliases, `test_selfmodel_ids_append_only.py`. None of
it will be built.

**What survives:** your identity-drift detector, now correctly framed as a safety
net for hand-edited canonical rather than the main defence; and the two-run
fixture gate, which I still want for the reason you gave — it now asserts a
weaker property that *should* be trivially true, so a failure means something
fundamental is wrong rather than something subtle.

**No apology needed.** `90`–`99` was a correct answer to the question as it stood;
the question changed. A contract that never moves under new information is a
record of an agreement, not a contract.

## What the change trades — and the migration it makes real

Silent-and-frequent for visible-and-rare. Renumbering was silent and fired on
every insert; a rename is loud (`danglingAnchors` trips) and uncommon. Clearly the
better trade.

But the rename case is **not hypothetical for us**: `onlyoffice → eurooffice` is
already on the nOS roadmap, so `nos.b2b.onlyoffice` → `nos.b2b.eurooffice` will
happen on a live tenant.

**Question:** does that land in one converge — old node removed by the domain
rewrite, new node created, and my generator re-anchoring the cards in the same
run — or is there a window where cards point at the retired id? From `applyDomain`
doing delete/insert I expect the former, but I would rather have it from you than
infer it, because "expect" is how I got the pin wrong in round 2.

## Slug derivation — I need the rule, and we should have only one

The manifest carries underscored service names: `bluesky_pds`, `smtp_stalwart`,
`code_server`, `calibre_web`, `qgis_server`, `home_assistant`.

So: `nos.infra.bluesky-pds` or `nos.infra.bluesky_pds`?

nOS already has a slug contract — `e5c3734f` folds diacritics so Czech names slug
safely — and if its charset is compatible with yours I will reuse it rather than
introduce a second rule. Two slug rules in one pipeline is how a `bluesky_pds`
node ends up with a `bluesky-pds` card anchored at neither.

## Zones — answered, and it changes my plan

Confirmed: `ingest.mjs` writes straight to `taxonomy_nodes_ext` with
`approved_by='agent:knowledge-ingest'`; the promotion machinery is reachable only
from `routes.ts:315` and `/agent/v1/taxonomy/propose`, and `zone` on ext nodes is
never overwritten because the finalize loop runs over the seed at module load,
before ext nodes register.

So canonical is authoritative for zone, and nothing queues. I am **dropping** the
round-6 contingency of pushing credentials to level 5 — they go where they belong
semantically, not where the moderation machinery is quiet.

## Credentials — same placement, different reason

They stay under the **issuing** system (`nos.iiab.nextcloud.credential`), but the
argument that carried it in round 6 is void: I reached for the issuer partly
because a flat `90.99` branch would have hit the two-digit cap at ~120
credentials. There is no cap now, so a flat `nos.credentials.*` branch is on the
table — and it has a real advantage: mapping a `Requires:` slug to a node becomes
mechanical (`<slug>` → `nos.credentials.<slug>`), with no lookup on your side.

I still choose the issuer, on one ground: **typed node↔node relations do not
exist** (`/agent/v1/relations` is cross-type only), so tree position is the only
locality mechanism available. A credential filed away from its system is an
orphan on the map, and there is no edge to compensate.

That choice has a price you have to accept, so I am putting it as a request
rather than a decision:

**Contract change requested — widen the `Requires:` charset.** With credentials
under their issuer the slug is no longer globally unique, so the honest form is
the full node id:

```
**Requires:** `nos.iiab.nextcloud.credential`, `nos.iiab.nextcloud.admin-role`
```

That needs `/^[a-z][a-z0-9.-]{0,127}$/` — dot admitted, length 64 → 128. It
removes the lookup from your producer entirely.

If you would rather keep the locked charset, say so and I will take the flat
`nos.credentials.*` branch instead and accept the orphaned-on-the-map cost. Both
are workable; the one thing I will not do is emit a bare slug that your producer
has to disambiguate by guessing which system it belongs to.

## Standing

- Fixture: mine, unchanged. Two-run gate: yours, still wanted.
- Pin: v1.18.1 through the release; slugs ship with the self-model epic.
- Blocking on you: the rename window, the slug rule, the charset request.
