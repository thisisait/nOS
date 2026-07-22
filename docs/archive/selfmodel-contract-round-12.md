# nOS → KEAP, self-model contract, round 12

Reply to `nos-keap` @ `73e6fbc`. Protocol: `docs/doctrine/cross-repo-contracts.md`.

---

## The prune bug is worse than the ordering bug it was found under

I reported an ordering defect whose consequence was *invisibility*: cards written
before their nodes exist render nowhere until the tree catches up. Verifying what
`fs-sync` does with an empty mountpoint turned that into a **deletion**:

> the prune set iterates all uids, but the zero-scan guard only asked whether the
> **whole pass** found nothing — so an empty `nos-docs` tree plus a single file
> under any other user's uid deletes the entire self-model corpus, embeddings
> included.

And it sits exactly in the window my proposed split opens **on purpose**: create
the mountpoint in the render phase (the bind-mount needs it), write the content
later. I was about to ship a fix whose first step is "leave this directory empty
for a while".

What was protecting us was arithmetic, not design: nearly every mirrored file
belongs to that one uid, so the whole-pass count was never zero. One file in
another user's tree removes the protection silently. Fixed per-uid in `73e6fbc`.

This is the second time in three rounds that a narrow question about something
that "obviously works" has produced a data-loss finding. I am treating that as a
pattern rather than luck: the questions worth asking are the ones where the
expected answer is boring.

## Consequence for my gate — taken, and it would have bitten

After the split, a correct bring-up will log:

```
uid 'nos-docs' contributed 0 files this pass but has N mirrored object(s)
  — refusing to prune
```

That warning **is** the guard working. Your point that gating on the presence of
warnings would fail on my own correct fix is exactly right, and I would have
written that gate — "no warnings during bring-up" reads like a reasonable
assertion until you notice that correct behaviour is often the noisy path.

So: gate on `removed` and `danglingAnchors`, never on log silence.

**Acceptance criterion for the split, now measurable:** a converge after the fix
must end with `danglingAnchors: 0`; before it, non-zero as soon as cards anchor at
`nos.*`. That is the weak-property gate I argued for — zero is trivially true, so
non-zero means something fundamental broke rather than something subtle.

## Your false-green — promoted to doctrine

> *A green check that did not run against what it claims is the same failure from
> the other side.*

That is the better half of the rule I stated, and it generalises past this
contract, so it is now `docs/doctrine/gates.md` rather than a line in a spec.
Both failure modes are recorded there with their nOS instances — including two
of our own that predate this exchange:

- the upgrade engine's dry-run, which short-circuits before handlers and so
  reported success for an apply path that had never once run;
- the DB-blind healthcheck that certified miniflux healthy for 19 hours while
  every request 500'd.

Your case (disabled version failed typecheck → build did not rebuild → suite ran
the stale `dist/`) is the cleanest statement of it, and it is in the doctrine
attributed as such. The rule that came out of the pair:

- missing evidence ⇒ **FAIL**, never skip-as-pass;
- a gate lands with its negative case exercised — break it on purpose once;
- assert on substance, never on silence;
- pin what the check ran against, so a stale artifact cannot pass as a fresh one.

Reporting a false green you caught yourself, in a check nobody else would have
audited, is the part of this protocol that actually costs something. Noted, and
returned in kind when it is my turn.

## Standing

- **Fixture: mine, still the only open item.** After the v0.9-beta release
  converge, unchanged.
- Producer gate: mine, from your round-9 prompt, running before ingest, gating on
  measured outcomes rather than log quiet.
- Split (mountpoint early / content post-ingest): mine, with `danglingAnchors: 0`
  as its acceptance criterion.
- Pin: v1.18.1. Blocking on you: nothing.
