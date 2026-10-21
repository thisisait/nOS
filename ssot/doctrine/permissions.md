---
in_force: false
ruled: null
row: rbac-permission-genome
gates:
  - tests/anatomy/test_an_app_states_one_tier.py
---
# Permissions — one genome says what each role may do

> **PROPOSED** (2026-10-21, roadmap row `rbac-permission-genome`). Not in force
> until the operator says so.
>
> Companion to [identity.md](identity.md) (WHO the accounts are)
> and [sso.md](sso.md) (HOW a service authenticates). This one owns WHAT a role may
> do. Inventory measured the same day over the repo: about 45 enforcement points in
> nine areas; roughly half restate the five group names as literals.

## 1. The rule

1. **One source.** `state/genome/permissions.yml` names every capability (a verb) and
   the roles that hold it. A role is a tier (1–4), an agent (`agent:<name>`) or a door
   (a named bearer: `door:face-bff`, `door:thalamus`, `door:wing-halt`,
   `door:ansible-provisioned`, `door:device`), plus `operator-local` (loopback break-glass).
2. **Every enforcement point reads its row.** Nothing names a group, a tier number or
   a scope the genome does not declare. Groups are the genome's projection into
   Authentik (`authentik_default_groups`), never a second definition.
3. **A capability is either enforced or absent.** A scope an agent declares and no
   tool or route checks is a lie in the manifest; the gate refuses it.
4. **One answer to "is this person tier 1?"** Today six places decide it (Wing
   `EndUser`, Wing `BasePresenter`, the thalamus, face `tier.ts`, KEAP internally,
   Authentik `is_superuser`), four of them hard-coded.
5. **A missing tier fails closed, the same way everywhere.** Today five defaults
   disagree (3, 2, 3, **1**, 4, deny).
6. **A reader prints it.** `tools/rbac-status.py`: the matrix (capability × role),
   then drift — each enforcement point's literal value against the genome — and
   UNKNOWN for a point it cannot read.

## 2. The vocabulary

**Tiers keep their meaning** (RBAC only; the dependency axis is `layer`,
[layers.md](layers.md)): 1 admin (`nos-providers`, `nos-admins`), 2 manager
(+ `nos-managers`), 3 user (+ `nos-users`), 4 guest (+ `nos-guests`).

**Proposed roles (operator decides, §5):**

| role | holds | never holds |
|---|---|---|
| contributor | proposals: an app draft, a KEAP edit, a roadmap row | enabling, deciding, any operator verb |
| moderator | the decision on proposals in ONE domain (`moderate:forum`, `moderate:keap-curation`) | anything outside that domain, any admin verb |

"moderator" exists today only as the forum's and the curator's own concept — no
group, no tier behind it.

**Capability families** (full list in the genome when it lands):
`app.reach:<slug>`, `app.admin:<slug>`, `app.role:<slug>=<role>`, `idp.superuser`,
`auth.mfa_required`; `identity.invite`, `identity.assign_tier`; `anatomy.view`,
`gdpr.read`, `breach.read`; operator decisions (`upgrade.apply`, `migration.apply`,
`patch.apply`, `coexistence.write`, `pulse.run_now`, `estate.halt`, `inbox.answer`,
`approval.decide`); `app.propose`, `app.enable`; `agent.start`,
`agent.session.read_all`; data (`table.create`, `table.write`,
`table.read@<visibility>`, `book.read_all`, `knowledge.write`, `capture.ingest`);
the agent runtime scopes (`wing.read`, `wing.write`, `keap.read`, `keap.write`,
`bash.read`, `inbox.ask`, `loop.propose`, `loop.judge`, `cortex.exec[...]`, ...);
`ruling.sign`.

## 3. Two token systems, one verb set

Wing bearer scopes (`wing.operator`, `wing.write`, `wing.halt`, `pulse.write`) and
Bone Authentik-JWT scopes (`nos:*:read|apply`) guard the same apply verbs twice. The
genome names the verb once; each system's scope is its spelling of it, generated.

## 4. Measured defects the genome would have prevented

Recorded as their own roadmap rows (security track), not deferred to the refactor:
- `apps/twofauth.yml`: `authentik.tier: 3` beside `nginx.rbac_tier: 1` ("only admins
  reach the TOTP secrets"); `authentik.tier` wins, so the app is user-tier.
- The `groups | last` idiom drops `nos-providers` from tier 1: GitLab `admin_groups`,
  the receptor identity map, the unix realm, JupyterHub `UNIX_REALM_GROUPS`.
- Node-RED makes every authenticated user an admin; only the tier-2 edge stands in front.
- `BasePresenter.php:378` cites a gate (`test_security_admin_gate_unchanged`) that
  does not exist.
- Declared, unenforced scopes: `events.write`, `audit.read`, `security.scan`,
  `pentest.execute`; Bone `nos:security:*`, `nos:pentest:execute`, `nos:devlog:write`.
- `nos-maintainers` (DGX bootstrap) is a group Authentik does not have.

## 5. Open for the operator

1. Contributor and moderator: both? Contributor between tiers 3 and 2, or a
   capability set on tier 3?
2. Moderator: a tier, or a per-domain capability granted to a person?
3. Doors and agents in the same genome as people, or a second file?

## 6. How it lands (roadmap `rbac-permission-genome` and its children)

Genome + reader first (reads the literals, prints drift — no behaviour change), then
one area per row, each flipping its literals to the genome with a gate shown red:
Authentik blueprints, plugin role maps, Wing, face, thalamus, KEAP, Bone + Pulse,
apps + manifest, DGX bootstrap. The doctrine goes in force with the first gate.
