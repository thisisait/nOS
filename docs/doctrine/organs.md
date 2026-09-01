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

## 3. Three axes, one map

| axis | question | today |
|---|---|---|
| `stack` | where it runs | complete, `state/manifest.yml` |
| `organ` | what it is for | 63/65, lives in `files/anatomy/apex/ruling.yml` as `publish:` |
| `layer` | what breaks without it | 26/65 — L0 3, L1 4, L2 19, **39 withheld** |

`organ` moves to the manifest; the apex ruling reads it instead of holding a
second copy. `layer` stays derived from the dependency graph.

**They are not interchangeable.** `archive` holds cortex and keap beside kiwix
and calibre-web; `spine` holds bone and wing beside portainer. Organ answers
what a service is for. Only `layer` answers what the estate cannot start
without, and defaults are a necessity question.

## 4. Defaults derive; config only adds

    install_<svc> defaults true  iff  layer ∈ {L0, L1} or stack == host
    everything else                   false

~13 services, computed from the graph, so defaults cannot drift from it.
A hand-set `install_*: true` the graph does not justify fails its gate.

`config.yml` becomes additive: extra services, parameters, personalisation.
It never carries `false`.

`prune_disabled_overrides` is then deleted. Its ambiguity is that `false` means
both *never wanted* and *not this run*; with an additive config the enabled set
is always a declaration, and the prune needs no permission flag.

Profiles become additive too. `all-on` adds everything. `dev-minimal` stops
existing — it is the default.

## 5. Order of work

1. Survey the 39 services with no `layer`. Prerequisite, not a side effect.
2. `organ` into `state/manifest.yml`; apex reads it.
3. Derive the default set; gate defaults against the derivation.
4. Make `config.yml` additive; delete the 30 no-op restatements and the 2 `false`.
5. Delete `prune_disabled_overrides` and `profiles/dev-minimal.yml`.
6. Re-point the agent forge from GitLab to Gitea (`tools/loop-review.py`).
