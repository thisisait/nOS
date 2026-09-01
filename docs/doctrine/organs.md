# Organs — what one is, and where its name lives

> **PROPOSED, not settled.** This document names an ambiguity and offers axes;
> it does not yet own a rule. The operator settles §3 before anything cites it.
> Sibling of [`layers.md`](layers.md), which did the same for **tier**.

## 1. The problem

Measured 2026-09-01. The word **organ** carries **four** independent meanings,
and no two of them enumerate the same set.

| what it means | what it actually measures | where it lives |
|---|---|---|
| the anatomy metaphor | Bones · Wings · Pulse · Cortex, plus Veins/Tendons/Nerves | CLAUDE.md prose only — **no machine surface** |
| host-native | runs under launchd/systemd rather than in a container | `stack: null` in `state/manifest.yml` (13 services) |
| `nos.host.*` | derived from the row above | KEAP taxonomy, via `keap_selfmodel_gen.py` |
| public organ | a metaphorical grouping shown to strangers: spine · wits · archive · senses · voice · ledger · forge · reflexes · gatehouse · commons | `publish:` in `files/anatomy/apex/ruling.yml` (10 groups) |

The fourth spans both halves of the second: `publish: spine` holds Wing and Bone
(host) while `publish: archive` holds container services. So "organ" is a
runtime fact in one place and a narrative grouping in another, and the estate
uses one word for both.

## 2. What the ambiguity has already cost

**`ears` did not exist anywhere for as long as it existed.** `install_ears: true`
while `state/manifest.yml` had no entry, so it had no taxonomy node, no
self-model card and no route derivation. Nothing noticed, because no reader
enumerates "the organs" — each of the four lists is complete on its own terms.

**`cortex` names two different things.** The host daemon is `nos.host.cortex`
(`stack: null`, the typechecker). CLAUDE.md also calls KEAP "the cortex — the
knowledge layer of the brain", and KEAP is `nos.iiab.keap`. Both are correct in
their own vocabulary and they are not the same component.

**`face` and `apex` are called organs and are not host-native.** They run as
`iiab-face-1` and `iiab-apex-1`, so the manifest and the taxonomy place them at
`nos.iiab.*` — correctly, because the generator's `host` bucket means "needs the
host's own filesystem, devices or network stack". An operator asking for
`nos.host.face` is using meaning 1; the tree answers in meaning 2.

**`agents` / caddy / jeff has no node in any of the four.** Two committed
`state/keap-tables/*.table.yml` anchored `[[nos.agents]]`, which exists nowhere,
and the KEAP lint reported it as a broken anchor for as long as they were there.

**`iiab` is a legacy stack name** still carried by the taxonomy of every service
in that stack.

## 3. The axes, proposed — the operator settles this

The `layers.md` precedent is to give each axis its own word and let none of them
be "organ" unqualified.

1. **runtime placement** — `host` vs `<stack>`. Already exists as manifest
   `stack`; needs no new word, only the discipline of not calling it organhood.
2. **anatomy role** — the Bones/Wings/Pulse/Cortex vocabulary. Has no machine
   surface at all. Either it gains one (a manifest field) or it is retired to
   prose and stops being cited as though it enumerates something.
3. **public organ** — the apex `publish:` grouping. Already machine-readable and
   already the only one with a gate behind it.

Open questions, none of which an agent should answer alone:

- Does the anatomy vocabulary become a field, or does the public grouping
  absorb it? Two metaphors for one estate is the ambiguity, not the fix.
- Is a grouping node like `nos.host.agents` wanted? The self-model generator is
  strictly two-level (stack → system) and manifest-driven, so a third level is
  a real change to `keap_selfmodel_gen.py`, not a content edit.
- Does `iiab` get renamed? That reaches compose project names, container names
  and every `nos.iiab.*` id — and the nightly `cortex-corpus-diff` compares
  taxonomy id sets both ways, so a rename reads as mass deletion unless staged.

## 4. What must be true whatever is chosen

**One reader enumerates the organs.** The reason `ears` went missing is that
four lists were each internally complete. Whatever the settled axis is, it needs
a reader that can be asked, in the shape of `tools/estate-status.py` — not a
list in prose that a fifth document will restate.
