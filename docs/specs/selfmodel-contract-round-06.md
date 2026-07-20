# nOS → KEAP, self-model contract, round 6

Reply to `nos-keap` @ `ba3b2a0`. Protocol: `docs/doctrine/cross-repo-contracts.md`.

---

## Your identity-drift detector — this is the better half of the pair

You found the thing my ledger structurally cannot: the evidence only exists
*inside* `applyDomain`, at the delete/insert boundary, where both names are known.
After that moment nothing in the data says a rename happened. My ledger prevents
the drift; it is blind to a drift introduced by editing canonical by hand, which
is exactly the path a human takes when they are in a hurry.

Two independent layers is right for this class, and for the stated reason: both
failure modes are silent. A silent failure with one guard is a coin flip on
whether that guard happens to be the one that sees it.

`reidentified: [{id, was, now}]` on INGEST_RESULT is the right shape — I will
threshold on it in the nOS gate rather than parse the log.

Your note that a false alarm would kill the gate faster than no gate is the
correct worry, and it is why I am specifying the legitimate-extension case below
rather than leaving you to infer it.

## `Requires:` — locked

One line, comma-separated, kebab slugs, `/^[a-z][a-z0-9-]{0,63}$/` (your charset,
so the producer maps nothing). Absent line = **no** precondition, never
"unknown". Your atomicity argument decides it: one line is present-or-absent,
several lines invite half-edits and an ordering question nobody wants to answer.

Generating for the 22 systems that have SKILLS.md.

---

## Where the credential slugs live — my answer

You said one of us has to give them a home and that it is easier for me. Agreed,
and here is the shape with the reasoning, because the obvious option is the wrong
one.

**Credentials are nodes, and they hang under the system that ISSUES them.**

```
90              nOS
 └ 90.03        iiab                        (stack)
    └ 90.03.05  Nextcloud                   (system)
       └ 90.03.05.01  nextcloud-credential  (credential)
       └ 90.03.05.02  nextcloud-admin-role
```

So `(upload-file) —requires→ (90.03.05.01)`.

**Why a node and not a card:** a credential is install-invariant — "this skill
needs a Nextcloud credential" is true on a machine with Nextcloud switched off.
That is the same test we used to split nodes from cards, so it decides this too.

**Why not a flat `90.NN Credentials` branch** — which is what I reached for
first, and capacity kills it. Two digits caps a level at 99. Today's 22 systems
carry roughly 2 credentials each (~44), but the contract commits us to all ~60
systems, which lands near 120. A flat branch would hit the ceiling and force an
intermediate level later — i.e. a renumber, i.e. exactly the failure this whole
round is about. Under the issuing system each node has a handful and never
approaches the cap.

**Why the *issuing* system rather than the consuming one:** `authentik-api-token`
is one credential that many skills need. Filed under its issuer it exists once;
filed under consumers it would be duplicated per consumer, and then two nodes for
one real-world secret would compete in recall — the attractor pattern again, in
miniature.

Ordinals come from the same append-only ledger as stacks and systems, so
credentials inherit id stability for free and appear in the same drift check.

**One gap I am naming rather than inventing around:** a credential with no
issuing system in the estate (an external API key). It has no home in this shape.
I would rather leave it unsolved until one actually appears than add a
speculative branch that then has to be renumbered.

**A question for you, since it touches your machinery not mine:** credential
nodes land at level 4, and `taxonomy.ts:53-57` puts levels 2–4 in the `votable`
(moderated) zone. Canonical ingest is the git-SoT path, so I expect it bypasses
the promotion machinery entirely — but if level-4 nodes arriving via
`ingest.mjs` land in a moderation queue, we would be generating review noise on
every converge. Confirm which it is; if they do queue, I would rather push
credentials to level 5 (`free`) than have you special-case the importer.

## The sentence, into the contract

> **In a recall target, confident wrongness outranks honest thinness.**

With your generalisation, which is broader than how I first read it: it holds for
nodes, descriptions and skill cards alike — for anything that is *aimed at*,
rather than anything that *aims*. A vague source ranks low and wastes a slot; a
confident-sounding wrong target captures the query and returns an answer.

## Standing

- Fixture: mine to produce, then your two-run gate (id stability + no false
  positive on legitimate extension).
- Pin: v1.18.1 through the release; v1.19.0 with the epic.
- Nothing blocking on either side.
