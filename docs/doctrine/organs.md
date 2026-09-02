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

## 4. Defaults are declared and validated, not derived

    state/manifest.yml:  default: true | false          per service
    gate:                every L0/L1 service is true
                         no true service has a false upstream
                         a service with no layer carries a reason

Derivation was tried and refused on evidence:

| rule `layer ∈ {L0,L1} or stack == host` | result |
|---|---|
| traefik | **false** — the only edge proxy, and the only proxy on Linux |
| tailscale, bone, alloy | **true** via `stack == host` while their layer is *withheld* |
| gitea, cortex, mcp_gateway, onlyoffice, openclaw, influxdb | true because a consumer that is false needs them |
| mailpit, ntfy, rustfs | L0 — sinks read as substrate |
| count | 30 of 65, against ~13 predicted |

`stack == host` reads a refusal as a yes. A one-pass computation over the full
manifest cannot express "needed only by something not enabled". Declaration
plus a gate expresses both.

## 5. Census after survey

L0 9 · L1 11 · L2 39 · withheld 6 — from 3/4/19/39.

Withheld with a reason, not a gap: traefik and tailscale (reachability, zero
data edges); bone (2-cycle with wing); ears, iiab_terminal, opencode (no
plugin manifest to carry `depends_on:`).

`alloy` is L2: it ships everything and nothing consumes it.

## 5b. Enforcement: stopping is not deleting

One flag guards two risks. `tasks/stacks/prune-disabled.yml` behind
`prune_disabled_overrides` does both:

    file: state: absent   on the compose fragment   — the converge can no longer recreate it
    docker rm -f          on the container          — gone, with its logs

So the SAFE half is gated behind the DANGEROUS half's permission, and with the
flag off — the only setting a profile run can use — nothing enforces the
declaration at all. MEASURED 2026-09-02: `install_gitlab: false` in config.yml,
and a reboot brought GitLab back, because nothing had stopped it.

Split them:

| declared off | action | reversible | gate |
|---|---|---|---|
| service is not in the enabled set | `docker stop` | yes | none — always runs |
| operator removed it deliberately | fragment + `rm -f` | no | explicit, per run |

`restart: unless-stopped` is what makes this work and it is already on every
container: an explicitly stopped container **stays stopped across a reboot**.
Stopping is therefore durable, cheap and undoable, and needs no permission flag.

`prune_disabled_overrides` then guards only deletion, which is what its name
says, and the enabled set is enforced on every converge instead of never.

## 6. Order of work

1. `organ` into `state/manifest.yml`; apex reads it.
2. `default:` into `state/manifest.yml`; gate it against the graph.
3. `config.yml` additive; drop the 30 no-ops and the 2 `false`.
4. Delete `prune_disabled_overrides` and `profiles/dev-minimal.yml`.
5. Plugin manifests for ears, iiab_terminal, opencode.
6. Decide the sink class: refuse it as edges the way exporters are refused, or accept 4 more default-on.
7. Agent forge to Gitea (`tools/loop-review.py`).
