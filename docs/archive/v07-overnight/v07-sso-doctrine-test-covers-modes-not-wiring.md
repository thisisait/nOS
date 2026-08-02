# v0.7 plan — SSO doctrine test covers *mode labels*, not *wiring*

Status: **PLAN — do not implement yet.** Review-ready.
Branch: `feat/v0.7-overnight`
Owner-gate: every code change ships with a `tests/anatomy/` gate; suite stays
green; `ansible-playbook main.yml --syntax-check` stays clean.

---

## 1. Problem / why

`tests/anatomy/test_sso_doctrine.py` is the canonical gate for the β1.A
three-bucket SSO doctrine (`native_oidc` / `header_oidc` / `forward_auth` /
`none`). Today it pins the **label** and only the label:

- `test_every_plugin_uses_canonical_authentik_mode` — the string is one of the
  four canonical spellings.
- `test_plugins_with_authentik_block_have_explicit_mode` — a plugin with other
  `authentik:` fields also declares `mode`/`provider_type`.
- `test_plugin_clients_have_consistent_naming` — `client_id` matches `nos-<slug>`.

What it **never checks**: that the declared mode matches the *actual wiring* the
playbook renders for that service. A plugin can say `mode: native_oidc` while
its compose-extension emits zero OIDC env (so the service has no login button),
or say `mode: forward_auth` while the middleware-driving map (`traefik_auth_modes`)
leaves it ungated. The label and the behaviour are two independent sources of
truth that drift silently. A typo-spelling gate passes green while the live
service is wide open or double-login broken.

**There are (at least) three independent sources of truth for a service's SSO
mode, and nothing cross-checks them:**

| # | Source of truth | Drives | Validated today? |
|---|-----------------|--------|------------------|
| 1 | `plugin.yml::authentik.mode` (Tier-1) / `apps/*.yml::authentik.mode` (Tier-2) | doctrine label, Authentik provider type, autologin legality | **only the spelling** |
| 2 | `roles/pazny.traefik/vars/main.yml::traefik_auth_modes[<id>]` | whether the Traefik **file** provider attaches `authentik@file` forward-auth (`proxy`) or not (`oidc`/`none`) — Tier-1 | **no** |
| 3 | compose-extension template OIDC env (`*_OAUTH_*` / occ / API) for `native_oidc`; `nginx.auth` in `apps/*.yml` → docker-provider middleware for Tier-2 | the actual app-level / edge behaviour | partially (see below) |

The complement gate (`test_native_oidc_no_authentik_middleware.py`) already pins
*one half* of the native_oidc invariant: a `native_oidc` plugin must NOT emit
`authentik@file` in its **compose-extension labels** (no double-login). But it
does NOT check the **`traefik_auth_modes` file map** (source #2, the real
middleware driver for Tier-1), and there is no gate at all for the
`forward_auth`/`header_oidc` direction (a gate service that is silently
*un*gated). So the existing coverage is asymmetric and label-only.

### Live evidence the drift is real (read-only audit, no mutation)

Cross-checking source #1 against source #2 today (`plugin.authentik.mode` →
expected `traefik_auth_modes` by the documented mapping
`native_oidc→oidc`, `forward_auth→proxy`, `header_oidc→proxy`, `none→none`)
surfaces **5 services where the two disagree**:

| service | plugin `mode` | expected `traefik_auth_mode` | actual | verdict |
|---------|---------------|------------------------------|--------|---------|
| `onlyoffice` | `forward_auth` | `proxy` | `none` | **intentional** — DocServer is JWT-secured collab backend; forward-auth would break the OnlyOffice↔Nextcloud callback. Needs a *documented waiver*, not a silent disagreement. |
| `spacetimedb` | `forward_auth` | `proxy` | `none` | **intentional** — binary protocol, no HTTP route to gate. Waiver. |
| `woodpecker` | `forward_auth` | `proxy` | `oidc` | **intentional** — app-auth via Gitea OAuth; a forward-auth gate is the documented double-login anti-pattern AND 302s the playbook's own Woodpecker API post-wiring (see the long comment in `vars/main.yml`). Waiver. |
| `qdrant` | `forward_auth` | `proxy` | *(absent)* | **legit-by-architecture** — Tier-2 manifest app (`apps/qdrant.yml`); routed by the Traefik **docker** provider from `nginx.auth`, NOT the `traefik_auth_modes` file map. Falls through to the `proxy` default, so still gated — but the gate must KNOW to skip Tier-2 ids here. |
| `snappymail` | `forward_auth` | `proxy` | *(absent)* | same as qdrant — Tier-2, docker-provider. |

So: 3 are real, justified exceptions that currently live only as prose comments
(a reviewer renaming a service or refactoring the map could silently break them),
and 2 expose the Tier-1-vs-Tier-2 routing-path distinction that the gate must
encode. **None of these are caught by any test today.** That is the concrete gap
this plan closes: turn the prose into an enforced contract with an explicit,
reviewed waiver list.

---

## 2. Exact files to touch

### New test file (the actual deliverable)
- `tests/anatomy/test_sso_mode_wiring_coherence.py` **(new)** — the wiring-vs-label
  cross-check gate. This is the fix; everything else is supporting metadata.

### New waiver / contract data
- `tests/anatomy/sso_wiring_waivers.yml` **(new)** — the single, reviewed list of
  (service, reason) pairs where the plugin `mode` legitimately diverges from the
  `traefik_auth_modes` expectation (onlyoffice, spacetimedb, woodpecker), plus the
  set of Tier-2 service ids that are routed by the docker provider (so the Tier-1
  file-map check skips them). Plain YAML, stock loader, no Jinja. Keeping the
  waivers in a data file (not hardcoded in the test) makes future exceptions a
  one-line reviewed diff with a mandatory `reason:`.

### Files READ by the gate (no edits expected; edits only if the gate finds a real bug)
- `files/anatomy/plugins/*/plugin.yml` — source #1 (Tier-1 mode).
- `apps/*.yml` — source #1 (Tier-2 mode) + `nginx.auth` (source #3 for Tier-2).
- `roles/pazny.traefik/vars/main.yml` — `traefik_auth_modes` (source #2).
- `files/anatomy/plugins/*/templates/*.compose.yml.j2` — source #3 for Tier-1
  native_oidc (presence of OIDC env / API wiring signature).
- `state/schema/plugin.schema.json` — the `mode`/`provider_type` enum + the
  `oauth2≡native_oidc` / `proxy≡forward_auth` alias contract (asserted, so a future
  schema change that drops a bucket trips the gate).

### Doc (one pointer, no behaviour change)
- `files/anatomy/docs/plugin-wiring-capabilities.md` — append a short subsection
  "SSO mode ↔ wiring coherence" documenting the two-source-of-truth model and the
  waiver file. (Optional in the same PR; the test docstring is authoritative.)

**No production YAML/Jinja edits are required for the gate itself** — the 5
divergences are either justified (→ waiver entry) or architectural (→ Tier-2 skip).
The gate codifies today's reality; it does not change the running system.

---

## 3. Approach

A new gate file with focused, independent test functions. Each maps one
source-of-truth pair and asserts coherence, with the waiver file as the only
escape hatch (every escape carries a mandatory human-written `reason`).

### 3.1 `test_tier1_mode_matches_traefik_auth_mode` (the headline gate)
For every **Tier-1** plugin (`files/anatomy/plugins/<svc>-base/plugin.yml`) with
an `authentik.mode`:
1. Resolve its service id = `authentik.slug` with `-`→`_` (the convention
   `traefik_auth_modes` keys use).
2. Compute expected file-provider auth mode from the documented mapping:
   `native_oidc→oidc`, `forward_auth→proxy`, `header_oidc→proxy`, `none→none`.
3. Look up `traefik_auth_modes[id]` (default `proxy` for unlisted, per the file's
   own documented fallback).
4. Assert `actual == expected`, UNLESS `id` is in the waiver list (with reason) or
   in the Tier-2 docker-provider skip set.

This is the test that would have flagged the woodpecker/onlyoffice/spacetimedb
disagreements at author time. The waivers turn "silent prose comment" into
"reviewed list entry".

### 3.2 `test_native_oidc_plugins_actually_wire_oidc`
For every plugin with `mode: native_oidc`, assert its compose-extension template
(or, for file/API-driven services, its role `tasks/post.yml`) contains a
real OIDC wiring signature — i.e. at least one of a curated set of markers:
`_OAUTH_`, `_OIDC_`, `OAUTH2_`, `OPENID`, `GENERIC_OAUTH`, `social_login`,
`occ ... oidc`, `auth_oidc`, `OAUTH_PROVIDERS`, etc. (The marker set is derived
from the β1.A native_oidc survey — env-driven vs file/API-driven lists in
CLAUDE.md.) A `native_oidc` label with zero wiring signature = the service has no
login button = the label is a lie. Services that genuinely wire OIDC outside the
plugin tree (rare) go on a small, reasoned allowlist in the waiver file.

This closes the gap left by `test_native_oidc_no_authentik_middleware.py`: that
gate proves native_oidc plugins don't *over*-gate; this proves they actually
*do* wire OIDC.

### 3.3 `test_forward_auth_plugins_are_actually_gated`
For every Tier-1 plugin with `mode: forward_auth` (or `header_oidc`), assert it
resolves to `traefik_auth_modes == proxy` (the only value that attaches
`authentik@file`), unless waived. This is §3.1 specialized to the
"gate service must be gated" direction — the security-critical half (a
forward_auth service silently mapped to `none`/`oidc` is **ungated** = the exact
class of bug that bit Infisical pre-2026-06-02, live-verified UNGATED).

### 3.4 `test_tier2_mode_matches_nginx_auth`
For every Tier-2 app (`apps/*.yml`) with `authentik.mode`, assert the
docker-provider auth path agrees: `mode: forward_auth|header_oidc` ⇒ effective
`nginx.auth` must be `proxy` (default is `proxy`, so this catches an explicit
`nginx.auth: none|oidc` that contradicts a `forward_auth` label). `mode:
native_oidc` ⇒ `nginx.auth` `oidc`/`none`. Mirrors §3.1 for the Tier-2 render path
(`files/anatomy/library/nos_apps_render.py::_auth_mode` + `_traefik_labels`).

### 3.5 `test_schema_enum_pins_canonical_buckets`
Assert `state/schema/plugin.schema.json` still enumerates exactly the four mode
buckets and the `provider_type` alias set including `oauth2`/`proxy`. This pins
the alias contract the cross-check relies on, so a schema edit that drops a bucket
fails loudly instead of making the gate's mapping table silently incomplete.

### Waiver file shape (`tests/anatomy/sso_wiring_waivers.yml`)
```yaml
# Reviewed exceptions where plugin authentik.mode legitimately diverges from
# the traefik_auth_modes expectation. Every entry needs a reason. Adding one
# is a deliberate, reviewed decision — not a way to silence a real bug.
tier1_auth_mode_waivers:
  onlyoffice:  "DocServer JWT-secured collab backend; forward-auth breaks the OnlyOffice<->Nextcloud callback"
  spacetimedb: "binary protocol, no HTTP route to forward-auth gate"
  woodpecker:  "app-auth via Gitea OAuth; forward-auth = documented double-login anti-pattern + 302s the API post-wiring"
# Tier-2 manifest apps routed by the Traefik DOCKER provider (nginx.auth),
# not the traefik_auth_modes file map — skip them in the Tier-1 file-map check.
tier2_docker_provider_ids:
  - qdrant
  - snappymail
native_oidc_external_wiring:  # native_oidc whose OIDC is wired outside the plugin tree
  []  # none today; reasoned entries only
```

---

## 4. Risks

- **False positives from the OIDC-marker heuristic (§3.2).** File/API-driven
  native_oidc services (Gitea Admin API, Nextcloud `occ`, Portainer `PUT`,
  Jellyfin/HA plugins) wire OIDC in `tasks/post.yml`, not the compose template.
  *Mitigation:* the marker scan covers BOTH the plugin templates AND the role
  `tasks/post.yml`; anything that still slips goes on the small reasoned
  `native_oidc_external_wiring` allowlist. Keep the marker set broad enough to
  avoid churn but specific enough to catch a genuinely-empty template.
- **Id-mapping fragility.** The slug→id (`-`→`_`) convention is assumed. If a
  plugin's `slug` and its `traefik_auth_modes` key ever diverge by more than the
  dash/underscore swap, the gate would false-positive as "unmapped".
  *Mitigation:* treat "plugin mode present but id not found in `traefik_auth_modes`
  AND not in the Tier-2 skip set" as its own assertion with a clear message
  ("service X declares mode but has no traefik_auth_mode and isn't Tier-2") — this
  is itself a real coverage gap worth surfacing, not a test bug.
- **Over-fitting to today's 5 divergences.** The waiver list encodes a snapshot.
  *Mitigation:* that's the point — every future divergence becomes a reviewed
  one-line diff with a `reason`. The gate fails closed on un-waived drift.
- **Zero live-system risk.** Read-only over repo files. No playbook run, no Docker,
  no API writes. Cannot touch the operator's running stack.

---

## 5. Gates (what pins this fix)

The deliverable **is** a gate, so the gate-for-the-fix is the test itself plus the
existing suite staying green:

1. `tests/anatomy/test_sso_mode_wiring_coherence.py` (new) — all functions in §3.
2. Existing complement gates remain green and unmodified:
   - `tests/anatomy/test_sso_doctrine.py` (label spelling — unchanged)
   - `tests/anatomy/test_native_oidc_no_authentik_middleware.py` (no over-gating)
   - `tests/anatomy/test_no_dup_traefik_router_labels.py`,
     `test_autologin_only_for_native_oidc_services.py` (mode-dependent siblings)
3. `tests/anatomy/test_config_stock_jinja_only.py` — N/A (no new
   `default.config.yml`/`default.credentials.yml` var; the waiver file is a
   test-only YAML, stock loader). Confirm no new prod var is introduced.

---

## 6. Verification recipe

All read-only; safe to run unsupervised.

```bash
cd /Users/pazny/projects/nOS

# 1. The new gate passes (and demonstrably FAILS first if you remove a waiver —
#    prove it catches drift by temporarily deleting the woodpecker waiver entry).
python3 -m pytest tests/anatomy/test_sso_mode_wiring_coherence.py -q

# 2. The whole SSO-doctrine cluster stays green.
python3 -m pytest \
  tests/anatomy/test_sso_doctrine.py \
  tests/anatomy/test_native_oidc_no_authentik_middleware.py \
  tests/anatomy/test_no_dup_traefik_router_labels.py \
  tests/anatomy/test_autologin_only_for_native_oidc_services.py \
  tests/anatomy/test_sso_mode_wiring_coherence.py -q

# 3. Full anatomy suite stays green (no collateral).
python3 -m pytest tests/anatomy -q

# 4. Stock-Jinja gate (proves no rogue prod var was added).
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q

# 5. Playbook still parses.
ansible-playbook main.yml --syntax-check

# 6. (Manual sanity) Re-run the audit that surfaced the 5 divergences; with the
#    waivers in place it should report ZERO un-waived mismatches.
```

**Falsifiability check (mandatory before merge):** temporarily flip
`onlyoffice` in `traefik_auth_modes` from `none` to `proxy` (a real bug — it would
break the DocServer callback) WITHOUT updating the waiver, and confirm the gate
goes RED. Revert. A gate that can't be made to fail isn't a gate.

---

## 7. Out of scope (explicit)

- Refactoring away the two-source-of-truth design (collapsing `traefik_auth_modes`
  into a derived value from plugin `mode`). That's a larger structural change with
  its own blank-run risk; this plan pins the *current* coherence so a future
  collapse has a safety net. Note it as follow-up tech-debt.
- Any live-system change. This is a repo-only test addition.
- Touching the `{{ vars }}` eager-resolve surface — the waiver YAML is test-local
  and never enters the plugin-loader namespace.
