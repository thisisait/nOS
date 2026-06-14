# Plan — Gov P0: ISDS + NIA/eIDAS federation (greenfield scaffold)

**Status:** PLAN (not implemented). Branch: `feat/v0.7-overnight`.
**Owner:** pazny. **Confirmed item:** `v07-gov-p0-isds-niaeideas-greenfield`.
**Class:** the two remaining structural gov P0 blockers — Czech **datové schránky
(ISDS)** statutory delivery + **NIA / eIDAS** citizen-identity federation. Both are
classified greenfield + external-dependency in
`docs/compliance/gov-readiness-audit-2026q2.md` (P0-8, P0-9) and
`docs/archive/gov-readiness-batch-plan.md §5` ("OPERATOR DECISIONS — DO NOT
auto-build"; needs an external MoJ ISDS endpoint + NIA SeP node + qualified
signing/encryption certs).

> **Hard scope boundary — read first.** Tonight's run is **unsupervised, repo-only,
> live-system READ-ONLY, no network**. ISDS and NIA *cannot* be live-validated here
> (no MoJ ISDS WSDL endpoint, no NIA SeP node, no qualified certs, no public DNS).
> Therefore this item ships **dormant scaffolding** — a default-OFF, gate-pinned,
> fail-loud wiring skeleton in the **exact pattern the MFA P0 already proved**
> (`files/anatomy/plugins/authentik-base/blueprints/50-mfa-policy.yaml.j2` + flag in
> `default.config.yml` + `profiles/gov-local.yml` opt-in + a `tests/anatomy/` gate
> that renders the blueprint in both flag states). The deliverable is **buildable,
> CI-pinned, byte-inert when off, and one operator credential-set away from going
> live** — NOT a live federation. That is the only honest, gateable, non-destructive
> shape for this item under the overnight rules. Anything requiring the external
> endpoints/certs stays an explicit operator step in the new profile + runbook.

---

## 1. Problem / why

A Czech *orgán veřejné moci* (public-administration controller) cannot deploy nOS
because two foundational integration surfaces are **wholly absent** — the audit
scores them 22/100 (eGovernment) and 14/100 (eIDAS), the two lowest dimensions, and
both held *flat* through the entire 2026-06-01 gov/GDPR batch:

1. **ISDS (datové schránky)** — the **legally mandatory** statutory electronic-delivery
   channel. An *orgán veřejné moci* MUST send/receive *datové zprávy* and archive
   delivery confirmations into a tamper-evident audit trail. nOS has **zero code** —
   no send/receive, no delivery-confirmation capture, no audit lineage.
2. **NIA / eIDAS federation** — Authentik today is wired **exclusively as an IdP
   issuing identity *down***; it never federates *up* to NIA (Identita občana) /
   eIDAS. There is no `authentik_sources_saml` / `authentik_sources_oauth`, no
   eIDAS minimum-dataset / **LoA** (`AuthnContextClassRef`) property-mapping, no
   LoA-gated step-up. The **MFA prerequisite** (an eIDAS LoA-substantial precondition)
   *did* ship in the gov batch and is live-wired — so the **one architectural
   dependency is satisfied**, and federation is now the next buildable layer.

**Why scaffold now, why not full live build:** the prior batch plan deliberately
parked both as operator decisions because the live build needs **external resources
this overnight run cannot touch** (MoJ ISDS production/test endpoint + ISDS box
credentials; NIA SeP node + ÚOOÚ-registered relying party + qualified eIDAS
signing/encryption certs; public DNS for the SAML/OIDC redirect). What *can* be built
tonight — repo-only, gated, byte-inert — is the **dormant wiring** so that:

- the eIDAS LoA / minimum-dataset **property-mapping shape is committed and
  CI-pinned** (the part that is pure Authentik-blueprint authoring, no external dep),
- the **federation source object** renders correctly with placeholder (fail-loud)
  external coordinates, so flipping it live is a credential-set + cert-mount, not a
  greenfield build,
- the **ISDS Art-30 record + audit event types + erasure/retention metadata** exist
  (the GDPR-register / audit-lineage surface that *is* repo-only),
- a **`profiles/gov-federation.yml`** (or an extension of `gov-local.yml`) carries the
  opt-in flag + documents every external operator step the profile cannot express as
  a var,
- a **runbook** (`docs/compliance/isds-nia-eidas-integration.md`) captures the live
  cutover recipe + the honest "what is scaffold vs live" boundary.

This converts "two greenfield blockers with zero code" into "two **default-OFF,
gate-pinned scaffolds** whose only remaining gap is operator-supplied external
endpoints/certs" — the same honest posture the MFA / at-rest / breach P0s landed in
(present + opt-in + inert-until-configured), and it raises the demonstrability floor
(an auditor can read the committed eIDAS LoA mapping + ISDS Art-30 record + audit
event taxonomy) without any false "it's done" claim.

---

## 2. Scope (explicit)

**In scope (repo edits only — live system stays READ-ONLY, no network):**

- **NIA/eIDAS federation blueprint** — a new
  `files/anatomy/plugins/authentik-base/blueprints/55-nia-eidas-source.yaml.j2`,
  gated behind a new `federate_nia` flag, Jinja-body-wrapped so it renders to
  `entries: ` (no objects, harmless no-op) when off — *byte-identical* safety
  mechanism to the `50-mfa-policy.yaml.j2` wrap. Contains: an
  `authentik_sources_saml.samlsource` (or `authentik_sources_oauth.oauthsource`
  for the OIDC-flavoured NIA endpoint — see §3.1 decision), eIDAS minimum-dataset +
  **LoA** (`AuthnContextClassRef` / `loa`) `propertymapping` objects, and the
  source-bound enrollment/authentication flow reference. External coordinates
  (`sso_url`, `slo_url`, `issuer`, signing-cert ref) come from **unset, fail-loud**
  config vars (render aborts loud if `federate_nia` is true but a coordinate is the
  placeholder sentinel — the at-rest-gate pattern).
- **ISDS Art-30 + audit-lineage scaffold** — an Art-30 processing record for the
  ISDS delivery activity (via the canonical `gdpr:` block path so
  `nos_gdpr.py` picks it up), new ISDS audit event types declared in the Wing schema
  extension (`isds_message_sent` / `isds_message_received` /
  `isds_delivery_confirmed`), and an erasure-map / retention-metadata entry. **No
  send/receive client code** (that is the live external build) — only the
  repo-only register + audit-taxonomy + retention surface.
- **Config + profile + flags** — new `federate_nia` (default `false`) +
  `install_isds_register` (default `false`) in `default.config.yml`, the external
  NIA coordinate vars as **placeholder sentinels** in `default.config.yml` /
  `default.credentials.yml` (real stock-Jinja defaults — see §5 trap), and a
  `profiles/gov-federation.yml` opt-in overlay (or a clearly-labelled section added
  to `gov-local.yml`) that flips the flags + documents the external operator steps.
- **Gate** — a `tests/anatomy/test_gov_federation_scaffold.py` modeled 1:1 on
  `test_mfa_blueprint.py` (render-clean both flag states, flag-OFF no-op, flag-ON
  shape = NIA source + eIDAS LoA mapping + fail-loud-on-placeholder; ISDS Art-30
  record present + audit event types declared).
- **Runbook** — `docs/compliance/isds-nia-eidas-integration.md` (live cutover recipe
  + scaffold-vs-live boundary) and a one-line status flip in
  `docs/compliance/gov-readiness-audit-2026q2.md` §(b) P0-8/P0-9 from "OPEN,
  greenfield, no code" to "scaffold shipped, default-OFF; live = operator external
  deps" (the honest delta — NOT a "closed" claim).

**Out of scope (do NOT do tonight — separate items / need live + external deps the run
forbids):**

- **Any live ISDS send/receive client** — the MoJ ISDS SOAP/WSDL integration
  (`mojeID`/ISDS box auth, message envelope build, delivery polling) needs a real
  endpoint + credentials. **Surface/register/audit-taxonomy only tonight.**
- **Live NIA/eIDAS handshake** — registering the relying party with NIA SeP,
  mounting qualified signing/encryption certs, the public-DNS redirect binding, and
  any live LoA-substantial sign-in. **Blueprint shape + LoA mapping only; render
  validated offline via the loader jinja env, never applied to a running Authentik.**
- **BankID / MojeID sources** (P2 in the batch plan) — same federation machinery,
  but a separate relying-party registration; not this item.
- **Touching the live Authentik container / blueprints dir on the running host** —
  the scaffold renders into the repo + the gate validates via the loader jinja env;
  no `ak apply_blueprint`, no `docker compose`, no write to `~/stacks/`.
- **WCAG / accessibility statement / ISVS / NKOD** (eGovernment dimension's *other*
  gaps) — doc-only items in the batch plan's Batch 6; not this federation item.

---

## 3. Approach (exact files + edits)

### 3.1 NIA/eIDAS federation blueprint (the repo-only, gate-able core)

New file:
`files/anatomy/plugins/authentik-base/blueprints/55-nia-eidas-source.yaml.j2`

Mirror `50-mfa-policy.yaml.j2` structurally:

- **Header doctrine block** (no literal Jinja brace-tags in comments — the Jinja
  parser reads them even inside `#` YAML comments; the MFA file's header calls this
  out explicitly and we inherit the constraint).
- **Default-OFF safety = the Jinja body-wrap ONLY.** The authentik-base plugin
  `render_dir: provisioning.blueprints` renders EVERY `.j2` in the dir
  **unconditionally** (confirmed in `50-mfa-policy.yaml.j2`'s header + `plugin.yml`
  `provisioning.blueprints`), so this file always lands at
  `<stacks_dir>/infra/authentik/blueprints/55-nia-eidas-source.yaml`. With
  `federate_nia` false it renders to `entries: ` with **no list** → the blueprint
  engine applies zero objects (harmless no-op). The `if federate_nia ... endif` wrap
  around `entries:` is the SOLE gate — do not remove believing it is gated elsewhere
  (same footgun the MFA header warns about).
- **Flag-ON entries (the eIDAS shape, grounded in Authentik's source-blueprint
  surface):**
  1. **Source object** — `authentik_sources_saml.samlsource` (SAML is the eIDAS-node
     lingua franca; NIA SeP speaks SAML 2.0). Fields: `name`/`slug`
     (`nia-eidas`), `sso_url`, `slo_url`, `issuer` (our entity ID), `binding_type:
     redirect`, `name_id_policy` (persistent), `allow_idp_initiated: false` (the
     Authentik docs flag IDP-initiated as a security risk — keep it off), bound
     `pre_authentication_flow` / `authentication_flow` / `enrollment_flow`. **Decision
     to record in review:** SAML vs OIDC source — NIA exposes a SAML 2.0 SeP for
     eIDAS; default to `samlsource`. (Leave a commented `oauthsource` stub if the
     operator's NIA tenancy is the OIDC variant.)
  2. **eIDAS minimum-dataset + LoA property mappings** —
     `authentik_sources_saml.samlsourcepropertymapping` objects translating the eIDAS
     SAML attributes (PersonIdentifier, FamilyName, FirstName, DateOfBirth) +
     **`AuthnContextClassRef` → LoA** into Authentik user fields/attributes (the
     Context7 Authentik docs confirm the property-mapping expression shape, e.g.
     `properties.get("urn:oid:...")` and a Python expression returning the
     `AuthnContextClassRef` value). The LoA mapping is the eIDAS-distinctive piece and
     is **100% repo-only authoring** — no external dep — so it is the highest-value,
     fully-gate-able part of this item.
  3. **(optional) LoA-gated step-up policy** — an expression policy referencing the
     mapped LoA attribute, bound so that LoA-substantial is required for citizen-facing
     apps. Ship the mapping unconditionally; ship the binding only if it can be
     authored without a live flow pk (the MFA item learned that a null/invalid
     blueprint-bound target atomically rejects the WHOLE blueprint — so bind
     **conservatively or not at all**, exactly as the MFA password-policy binding was
     dropped; the gate pins "no fragile policybinding ships").
- **Fail-loud on placeholder** — the external coordinates (`nia_sso_url`,
  `nia_slo_url`, `nia_issuer`, `nia_signing_cert_ref`) carry a sentinel default
  (e.g. `"__UNSET__"`). When `federate_nia` is true the template **`| mandatory`**s
  them (stock Ansible filter) or, since this renders inside the loader's jinja env
  (not the `{{ vars }}` eager namespace — it is a `render_dir` template), uses a
  `{% if nia_sso_url == "__UNSET__" %}{# raise via a deliberate undefined #}{% endif %}`
  fail-loud guard. The gate asserts flag-ON-with-placeholder renders an
  obvious-broken / raises (so a half-configured gov run aborts loud rather than
  registering a NIA source pointing at a placeholder URL). This is the at-rest-gate
  doctrine (`tasks/preflight-at-rest.yml` hard-fails on missing precondition).

### 3.2 ISDS Art-30 + audit-lineage scaffold (repo-only register surface)

- **Art-30 record** — author an ISDS delivery processing activity via the canonical
  `gdpr:` block path so `files/anatomy/module_utils/nos_gdpr.py` harvests it into the
  Art-30 register (`state/dpa-register.md` + Wing's `gdpr_processing`). Either a small
  `isds-register-base` plugin manifest (`files/anatomy/plugins/isds-register-base/
  plugin.yml`) carrying only a `gdpr:` block (no compose — it is a register-only
  scaffold gated by `install_isds_register`), OR — if a plugin with no service is
  awkward — a dedicated entry in the host-service register path. **Decision for
  review:** prefer the plugin-manifest `gdpr:` block (it reuses the CI-pinned
  `test_gdpr_register_coverage.py` machinery and the `nos_gdpr.py` mapper rather than
  inventing a parallel path). Full Art-30(1) dims: purpose (statutory electronic
  delivery, *zákon č. 300/2008 Sb.*), legal_basis (`legal_obligation`), data
  categories, data subjects, retention horizon, processors, EU-residency.
- **Audit event types** — declare `isds_message_sent`, `isds_message_received`,
  `isds_delivery_confirmed` in the Wing event taxonomy alongside the existing
  `agent_*` types (`files/anatomy/wing/db/schema-extensions.sql` event-type doc / the
  declared-types surface) so a future live ISDS client emits into the tamper-evident
  chain. **No emitter code** — only the declared types + their place in the audit
  lineage (so the chain + Art-30 retention reach them once live).
- **Retention / erasure metadata** — an entry in `state/gdpr-erasure-map.yml`
  (method: manual, with the statutory-archival exception noted — ISDS *datové
  zprávy* have a legal retention that overrides erasure, the Art-17(3)(b) legal-
  obligation carve-out) so the coverage gate does not flag a silent gap. Descriptive
  metadata, honestly marked `method: manual` (consistent with the audit's honesty
  doctrine — never overstate automation).

### 3.3 Config + profile + flags

- `default.config.yml`: `federate_nia: false`, `install_isds_register: false`, and
  the NIA external-coordinate vars as placeholder sentinels (`nia_sso_url: "__UNSET__"`
  etc.) — **every one a real stock-Jinja default** (string literal, no non-stock
  filter), defined in `default.config.yml` so it loads BEFORE the core-up loader
  (the `{{ vars }}` eager-resolve trap — see §5).
- `default.credentials.yml`: if any NIA coordinate is a secret (signing-cert path /
  client secret for the OIDC variant), seed it as a placeholder using the standard
  `{{ global_password_prefix }}_pw_*`-style stock template, defined before core-up.
- `profiles/gov-federation.yml` (new) — opt-in overlay that sets `federate_nia: true`
  + `install_isds_register: true` and, in a `MANUAL STEPS` footer block (mirroring
  `gov-local.yml`'s footer), documents every external precondition the profile cannot
  express as a var: the MoJ ISDS box + credentials, the NIA SeP relying-party
  registration + qualified signing/encryption certs + cert mount path, the public-DNS
  redirect binding, and "set `nia_sso_url`/`nia_slo_url`/`nia_issuer` to your real NIA
  SeP coordinates before this flag does anything but fail loud." Layer note: `-e
  @profiles/gov-local.yml -e @profiles/gov-federation.yml` (later file wins).

### 3.4 No live mutation

Nothing here touches a running Authentik, a real ISDS endpoint, or `~/stacks/`. The
blueprint renders into the repo template tree; the gate validates the render via the
loader's own jinja env (`load_plugins._jinja_env()` — the production render path, no
Docker, no network, exactly as `test_mfa_blueprint.py` does). The Art-30 record flows
through the existing offline `nos_gdpr.py` mapper. The flags default OFF, so a normal
`ansible-playbook main.yml` run is byte-inert (blueprint renders to empty `entries:`,
ISDS register plugin disabled).

---

## 4. The gate (NON-NEGOTIABLE — every fix ships a gate)

New file: **`tests/anatomy/test_gov_federation_scaffold.py`**, modeled 1:1 on
`tests/anatomy/test_mfa_blueprint.py` (render via `load_plugins._jinja_env()`,
`!Find`/`!KeyOf` opaque YAML loader, no Docker / Authentik / network).

Tests:

1. `test_render_clean_both_flag_states` — render `55-nia-eidas-source.yaml.j2` with
   `federate_nia` True (placeholders *populated* with dummy non-sentinel coordinates)
   and False; both emit `version: 1`, no leftover `{{`/`{%`. (The MFA gate's
   anchor test.)
2. `test_flag_off_is_noop` — `federate_nia=false` → `entries` is `None`/`[]` (the
   default-OFF byte-inert guarantee — the single most important safety pin).
3. `test_flag_on_shape` — `federate_nia=true` (dummy coordinates) → entries contain
   exactly: one `authentik_sources_saml.samlsource` named `nia-eidas` with
   `allow_idp_initiated: false`; the eIDAS LoA `samlsourcepropertymapping` (assert the
   `AuthnContextClassRef`/LoA mapping is present — the eIDAS-distinctive piece); and
   the PersonIdentifier/FamilyName/FirstName minimum-dataset mappings.
4. `test_fail_loud_on_unset_coordinates` — `federate_nia=true` with a coordinate left
   at the `"__UNSET__"` sentinel → render **raises** (or emits an obvious
   broken/guard marker the gate asserts on). Pins that a half-configured gov run
   aborts loud rather than registering a NIA source pointing at a placeholder.
5. `test_no_fragile_policybinding` — no `authentik_policies.policybinding` with a
   null/invalid target ships (the MFA item's hard-won lesson: a bad blueprint-bound
   target atomically rejects the WHOLE blueprint). Same negative-assert as
   `test_mfa_blueprint.py::test_flag_on_shape`'s `pol_binds == []`.
6. `test_isds_art30_record_present` — the ISDS Art-30 record renders through
   `nos_gdpr.py` with all 7 dims populated (purpose non-boilerplate,
   `legal_basis == legal_obligation`, retention horizon set) when
   `install_isds_register` is on. (Reuses the `test_gdpr_register_coverage.py`
   harness shape.)
7. `test_isds_audit_event_types_declared` — `isds_message_sent` /
   `isds_message_received` / `isds_delivery_confirmed` appear in the Wing event-type
   declaration surface (so the future live client emits into the chain).
8. `test_isds_erasure_map_entry_with_statutory_exception` — the ISDS entry exists in
   `state/gdpr-erasure-map.yml` with the Art-17(3)(b) legal-obligation/statutory-
   archival exception noted (no silent coverage gap; honest `method: manual`).

Each test carries a surgeon-tone docstring naming the structural guarantee it pins.

**Why a gate and not just a fix:** doctrine is explicit — "If you cannot gate it, it
is a PLAN not a fix." The MFA P0 *is* the precedent: a federation/identity blueprint
is correct-by-inspection-renderable offline, and the loader-jinja-env gate pins the
default-OFF no-op + the flag-ON shape + the fail-loud guard without any live system.

---

## 5. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Stock-Jinja `{{ vars }}` trap** — a new NIA coordinate var referenced only via `\| default()` aborts the core-up eager resolve (the documented second-variant trap that bit `app_secrets`/`mysqld_exporter_password`) | med | Give EVERY new var (`federate_nia`, `install_isds_register`, all `nia_*` coordinates) a **real default in `default.config.yml`/`default.credentials.yml`** (loads before core-up) using **stock filters only**. `test_config_stock_jinja_only.py` is run in the verification recipe and pins both variants. |
| Blueprint renders unconditionally (render_dir is ungated) → an accidental non-empty `entries:` when off enforces a NIA source on every install | low (pinned) | The Jinja body-wrap is the SOLE gate (same as MFA); `test_flag_off_is_noop` pins `entries in (None, [])`. Header doctrine block warns against removing the wrap. |
| A fragile blueprint-bound policy/flow target with a null pk atomically rejects the WHOLE blueprint on a live apply | med (known footgun) | Inherit the MFA lesson: bind conservatively or not at all; `test_no_fragile_policybinding` negative-asserts. LoA step-up binding is optional and dropped if it needs a live pk. |
| Scaffold read as "ISDS/NIA done" → false demonstrability (the audit explicitly flags doc-vs-code falsehoods as a finding) | med | The runbook + the audit §(b) status flip say **"scaffold, default-OFF, live = operator external deps"** — NOT "closed". Plan title + header + commit body all say *greenfield scaffold*. No score uplift claimed beyond "buildable + pinned". |
| Literal Jinja brace-tag in a YAML `#` comment breaks the render (Jinja parses comments) | low | The MFA header documents this; mirror its no-brace-tag header style. `test_render_clean_both_flag_states` catches any leftover tag. |
| SAML-vs-OIDC source choice wrong for the operator's NIA tenancy | low | Default to `samlsource` (NIA SeP is SAML 2.0 for eIDAS); leave a commented `oauthsource` stub + a runbook note. Operator decision, documented. |
| Plugin-with-no-service (`isds-register-base`) confuses the loader / coverage gate | low | If awkward, fall back to a host-service register entry; the §3.2 decision prefers the manifest path because it reuses the CI-pinned `nos_gdpr.py` machinery. Pick in review; the gate accepts whichever lands. |
| Live system mutation | N/A — none | Repo edits only; gate validates via loader jinja env; flags default OFF; no `ak apply_blueprint`, no compose, no write to `~/stacks/`, no network. |

---

## 6. Deferred (explicitly NOT this item — operator + external deps)

- **Live ISDS send/receive client** — the MoJ ISDS SOAP/WSDL integration (box auth,
  message envelope, delivery polling, confirmation capture → audit emit). Needs a real
  ISDS endpoint + credentials. **Operator decision** (batch plan §5 P0-ISDS).
- **Live NIA/eIDAS handshake** — relying-party registration with NIA SeP, qualified
  signing/encryption certs + mount, public-DNS redirect binding, live LoA-substantial
  sign-in. **Operator + external dep** (batch plan §5 P0-NIA-EIDAS). MFA prerequisite
  is already satisfied.
- **BankID / MojeID sources** — same federation machinery, separate relying-party
  registration (batch plan §5 P2-BANKID-MOJEID).
- **eGovernment dimension's other gaps** — WCAG 2.1 AA + *prohlášení o přístupnosti*,
  ISVS register alignment, NKOD open-data path — doc-only items in the batch plan's
  Batch 6, not this federation item.
- **Live LoA-gated step-up enforcement** — ship the LoA *mapping* tonight; the live
  *enforcement* binding waits on a real NIA assertion to test against.

---

## 7. Verification recipe

All offline, no live system, no network — safe for unsupervised run:

```bash
cd /Users/pazny/projects/nOS

# 1. The new gate passes (run it BEFORE the §3 edits to confirm it RED-catches the
#    missing scaffold, then GREEN after — the MFA-gate discipline).
python3 -m pytest tests/anatomy/test_gov_federation_scaffold.py -v

# 2. The sibling gov gates stay green (no regression in the shared blueprint /
#    register / erasure-map machinery).
python3 -m pytest tests/anatomy/test_mfa_blueprint.py \
                  tests/anatomy/test_gdpr_register_coverage.py \
                  tests/anatomy/test_gdpr_erasure_map.py \
                  tests/anatomy/test_at_rest_gate.py -v

# 3. Stock-Jinja trap gate GREEN — proves every new var (federate_nia,
#    install_isds_register, nia_* coordinates) has a real default + stock filters
#    and resolves before the core-up loader (BOTH trap variants).
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q

# 4. Full anatomy suite stays green.
python3 -m pytest tests/anatomy/ -q

# 5. Playbook syntax-check clean (the new blueprint + plugin manifest + config vars
#    must not break render or parse).
ansible-playbook main.yml --syntax-check

# 6. Confirm default-OFF byte-inertness: render the blueprint with the flag off via
#    the loader jinja env and confirm empty entries (the gate does this, but a
#    manual spot-check is cheap). And confirm a normal config diff stays clean.
grep -n "federate_nia\|install_isds_register\|nia_sso_url" default.config.yml
grep -n "55-nia-eidas-source" files/anatomy/plugins/authentik-base/blueprints/ -r
```

Expected: gate #1 RED before §3 edits (proves it catches the missing scaffold), GREEN
after; #2–#5 GREEN throughout; #6 shows the flags defaulting `false`, the placeholder
coordinates present, and the blueprint file in place. **No live run, no network, no
`ak apply_blueprint`** — the federation never touches a running Authentik this item.

---

## 8. Commit shape (when implemented — separate from this plan commit)

```
feat(gov): scaffold ISDS + NIA/eIDAS federation (default-OFF)

- NIA/eIDAS SAML source blueprint (55-nia-eidas-source.yaml.j2),
  federate_nia-gated body-wrap; eIDAS LoA + minimum-dataset
  property-mappings (the repo-only, CI-pinnable core).
- fail-loud on placeholder NIA coordinates (at-rest-gate doctrine).
- ISDS Art-30 record + isds_* audit event types + erasure-map entry
  (statutory-archival Art-17(3)(b) exception); no live client.
- profiles/gov-federation.yml opt-in + external-dep operator steps.
- gate: test_gov_federation_scaffold pins both flag states + LoA shape.
```

(Conventional Commits, subject ≤50 chars, surgeon-tone body ≤6 bullets, no
Co-Authored-By, no `--author`, branch-only — never pushed. Live cutover stays an
operator step; this commit ships only the dormant, gate-pinned scaffold.)
