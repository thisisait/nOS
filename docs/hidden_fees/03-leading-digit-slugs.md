# 03 — A service name starting with a digit cannot be a KEAP node id

## The fee

KEAP node ids must match `^[a-z][a-z0-9-]*$` per segment — the **first character
must be a letter**. nOS's slug contract (`files/anatomy/face/src/lib/security/uid.ts`)
happily produces a digit-initial slug: `2FAuth` → `2fauth`.

The estate is clean today only because somebody already hit this and spelled
around it — the Tier-2 manifest is named `twofauth`, not `2fauth`. That fix is
invisible: nothing records *why* the file has that name, so the next person
naming a service after a number will not know the constraint exists.

The fee is that the workaround is undocumented and unenforced.

## When the bill comes due

The next service whose name starts with a digit — a `3d-printer` app, a
`7zip` tool, anything numeric-initial. The failure mode is the bad kind:
**silent.** KEAP drops a non-matching anchor without a word (`objects.ts`), so
the card attaches to nothing and simply never appears in the constellation. No
error, no log line, no failed task — just a system missing from the map that
nobody notices is missing.

## How it was found

Sideways, and only because the question was asked explicitly. While confirming
that nOS's existing slug contract satisfies KEAP's charset, the whole estate was
run through the rule rather than spot-checked — 51 Tier-1 services and 4 Tier-2
apps. All passed, and `twofauth` was the tell that the constraint was real and
had bitten before.

Had the check been "does the contract look compatible?", this would still be
unknown.

## What closes it

A gate in the producer that runs every emitted slug through the KEAP charset and
fails on a mismatch — planned as check (b) of the self-model producer gate:

> every emitted slug matches `/^[a-z][a-z0-9-]*$/` after diacritic folding,
> because KEAP drops a non-matching anchor silently

That converts a silent disappearance into a failed CI run. Until it exists, the
only thing standing between nOS and an invisible node is that nobody has named a
service after a number recently.

## Closed — 2026-07-26

The guard `slug_or_die` already lived in the producer
(`files/anatomy/scripts/keap_selfmodel_gen.py`); what was missing was proof it
fires. `tests/anatomy/test_selfmodel_slug_charset.py` now runs **every** manifest
service id and stack (63 + 9) through the KEAP charset and asserts a valid slug,
asserts a leading-digit name (`2fauth`, `3d-printer`) raises loudly, and pins the
pattern + diacritic fold. The silent-drop is now a red CI run.

The Cortex docs schema (`docs/archive/cortex-docs-schema.md` §5) routes every doc
node id through the same `slug_or_die`, so this gate covers docs too — there is
no second charset implementation to drift. Re-opens only if a new id-minting path
bypasses `slug_or_die`; the design forbids that (call the function, do not
re-derive the rule).
