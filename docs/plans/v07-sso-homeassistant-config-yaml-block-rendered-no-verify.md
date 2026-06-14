# Plan — Home Assistant SSO: close the config.yaml-block-rendered-no-verify gap

- Status: PLAN (not implemented)
- Branch: `feat/v0.7-overnight`
- Item: `v0.7 / sso / homeassistant-config-yaml-block-rendered-no-verify`
- Class: silent SSO failure — same family as the 2026-06-13 Nextcloud
  `user_oidc` / Portainer OAuth2 / Jellyfin `SSO-Auth.xml` root-cause: a config
  artifact gets *rendered* (`auth_oidc:` block lands in `configuration.yaml`),
  the playbook reports OK, but **nothing proves the provider actually loaded at
  runtime** — a dead "Sign in with Authentik" exits 0.
- Service tier: Home Assistant — Tier-3 (`authentik.tier: 3`), `mode:
  native_oidc` via the `auth_oidc` HACS community plugin
  (`christiaangoossens/hass-oidc-auth`). Button at minimum; `default_redirect`
  autologin when `sso_autologin*` is on.

---

## 1. Problem / why

`roles/pazny.homeassistant/tasks/main.yml` wires HA SSO across three host-side
renders, each of which **succeeds whenever the file is written**:

1. **Component landing** (lines 62–139) — download + extract the `auth_oidc`
   HACS component into `custom_components/auth_oidc/`. This surface IS already
   hardened: a `stat manifest.json` + a loud `debug` WARN if it's absent (the
   2026-06-13 dead-pin audit fixed the silent-drop). **Good — keep it.**
2. **`secrets.yaml` render** (lines 141–150) — writes `oidc_client_id` /
   `oidc_client_secret`. Succeeds on write; never validated against Authentik.
3. **`auth_oidc:` block injection** (lines 160–180) — `blockinfile` injects the
   `auth_oidc:` stanza (with `discovery_url`, `display_name: "Authentik"`,
   `features.include_groups_scope`, `features.default_redirect`) into
   `configuration.yaml`. **`blockinfile` reports `changed`/`ok` the instant the
   text lands — regardless of whether HA's strict `CONFIG_SCHEMA` accepts it.**

The gap is at surface #3 (and #2 by extension): the `auth_oidc:` block is
**rendered, never verified**. The role's own comment documents the exact
landmine that makes this dangerous (lines 169–174):

> v1.1.x schema: the 0.9-era `automatic_user_linking` / `automatic_person_creation`
> keys were REMOVED … and a strict `CONFIG_SCHEMA` rejects unknown keys —
> passing them makes HA refuse to load `auth_oidc`.

So the concrete silent-failure surfaces are:

- **Schema drift** — a future edit reintroduces a removed/unknown key (or a
  `homeassistant_auth_oidc_version` bump changes the schema). HA boots,
  `default_config:` still loads, the UI is up, `/api/onboarding` answers, smoke
  GETs `/` → 200 — but `auth_oidc` was rejected at config-load and the "Sign in
  with Authentik" provider **never registers**. The run is green; the operator
  discovers SSO is dead only by clicking the button (which 404s / shows no
  provider).
- **Discovery-URL drift** — `discovery_url` points at
  `https://{{ authentik_domain }}/application/o/homeassistant/.well-known/openid-configuration`.
  If the Authentik slug or `authentik_domain` drifts, the component loads but
  fails to reach the IdP; again no runtime signal in the playbook.
- **secrets.yaml `!secret` mismatch** — the block references `!secret
  oidc_client_id`; if the secrets keys are renamed on one side only, HA fails
  the `!secret` lookup at load → `auth_oidc` doesn't initialise. Silent.

Unlike Portainer (`/api/settings` → `AuthenticationMethod`, loud `failed_when`,
pinned by `test_portainer_sso_verify_loud.py`) and WordPress
(`test_wordpress_oidc_install_verified.py`), Home Assistant's `tasks/post.yml`
runs the onboarding + password reconverge but **never probes the OIDC provider
endpoint**. There is **no anatomy gate** touching HA SSO at all (`grep` over
`tests/` returns zero HA-SSO tests).

Net: HA is the native_oidc service whose config block is rendered-but-unverified
and ungated — the last uncovered member of the silent-SSO-failure class for
v0.7.

---

## 2. Exact files / roles to touch

Code (repo-only; live system stays READ-ONLY):

- **`roles/pazny.homeassistant/tasks/post.yml`** — add a **loud live OIDC
  provider verify** block at the END (after onboarding + password reconverge):
  - `meta: flush_handlers` (or re-poll `/` via `pazny._common_tasks
    wait_for_api.yml`) so the pending `Restart homeassistant` handler runs
    BEFORE the probe — otherwise we verify the pre-restart config state.
  - `ansible.builtin.uri` GET the auth_oidc provider's runtime endpoint
    (`/auth/oidc/welcome`, the plugin's entry route — **confirm exact path/case
    against `hass-oidc-auth` v1.1.1's `OIDCFlowHandler` routes before writing**;
    fallback candidate `/auth/oidc/redirect`). Expect the live shape (200 or a
    302 to Authentik); a config that failed to load makes HA **not register the
    route → 404**.
  - `failed_when:` asserts the status is in the live set AND is NOT 404 — NOT a
    bare `false`. Gate on `install_authentik | default(false)` and
    `_ha_ready.status` being live.
  - Mirror the Portainer ceiling: an **unverifiable** probe (endpoint
    unreachable / status 0 / 404) when `install_authentik` is on must FAIL loud,
    not soft-skip. (The component-landing WARN in `main.yml` is deliberately
    non-fatal because it runs early in stack-render and a hard fail there blocks
    every downstream service's post-wiring — but `post.yml` runs AFTER bring-up,
    so a hard fail here is safe and correct. Document this asymmetry inline.)
- **`roles/pazny.homeassistant/tasks/main.yml`** — OPTIONAL: pull the canonical
  `auth_oidc` config schema (allowed top-level + `features` keys for v1.1.1)
  into a single source of truth the render and the gate share. Preferred:
  `roles/pazny.homeassistant/vars/main.yml` (NEW) with
  `homeassistant_auth_oidc_allowed_keys` + `homeassistant_auth_oidc_features_keys`
  lists. The `blockinfile` body stays human-authored; the gate diffs the
  rendered keys against these lists so a removed/unknown key (the v0.9→v1.1
  landmine) fails a fast offline test instead of a live boot.
- **`roles/pazny.homeassistant/vars/main.yml`** (NEW, preferred) — the
  allowed-keys lists above. A role `vars/` file is OUT of the `{{ vars }}`
  pre-core-up eager-resolve namespace (the role is invoked during stack-up,
  after core-up), and these are static literal lists with no filters, so the
  stock-Jinja trap does not apply — but run `test_config_stock_jinja_only.py`
  anyway per the hard rule.
- **`state/smoke-catalog.yml`** — add a Home Assistant SSO smoke entry (there is
  NO HA-specific entry today; only the manifest auto-import baseline GET `/`).
  Probe the provider endpoint with `auth: anon`, `expect: [200, 302]` (a live
  provider answers / redirects to Authentik; a dead one 404s), gated `when:
  "install_homeassistant | default(false) and install_authentik | default(false)"`.
  This layers post-run / reconverge coverage on top of the role-run verify.

Tests (mandatory — a fix without a gate is a PLAN):

- **`tests/anatomy/test_homeassistant_sso_verify_loud.py`** (NEW) — pins the
  loud runtime verify in `post.yml`.
- **`tests/anatomy/test_homeassistant_auth_oidc_schema.py`** (NEW) — pins the
  rendered `auth_oidc:` block keys against the v1.1.1 allowed-keys list and
  explicitly forbids the historical landmine keys.

Docs:

- Update the `roles/pazny.homeassistant/tasks/main.yml` block comment (lines
  116–122 / 152–159) to point at the new `post.yml` verify (it stops being a
  "WARN only" story once a loud runtime probe backstops it).
- Update `roles/pazny.homeassistant/README.md` SSO section with the verify
  endpoint + break-glass note.

NOT touched: `files/anatomy/plugins/homeassistant-base/plugin.yml` (the
`authentik:` metadata block is correct — `mode: native_oidc`, tier 3, redirect
URIs, autologin). No live mutation. No compose change.

---

## 3. Approach

### 3.1 Loud live verify (kills the dead-provider-exits-0 surface)

In `tasks/post.yml`, after the existing onboarding/password flow:

- `meta: flush_handlers` so `Restart homeassistant` runs before the probe (HA
  must reload `configuration.yaml` to register the `auth_oidc` route). Verify the
  idempotence re-run stays `changed=0` — if flushing re-fires unrelated handlers,
  switch to a `wait_for_api.yml` re-poll of `/` instead of flushing.
- Re-poll `/` (reuse `pazny._common_tasks wait_for_api.yml`, `status_code: [200,
  302]`) so we don't probe mid-restart.
- `ansible.builtin.uri` GET
  `http://127.0.0.1:{{ homeassistant_port }}/auth/oidc/welcome`
  with `status_code: [200, 302]` and `follow_redirects: none`.
  - A LIVE provider answers 200 (welcome page) or 302 to Authentik's
    `/application/o/authorize/…`.
  - A config that failed `CONFIG_SCHEMA` → route not registered → **404**.
- `failed_when:` = status NOT in the live set (i.e. fail on 404 / 0). NOT a bare
  `false`. Guarded by `when: install_authentik | default(false) and
  (_ha_ready.status | default(0) in [200, 302])`.
- An unreachable / 0-status probe under `install_authentik` is a hard fail
  (Portainer ceiling), NOT a soft skip — the whole point is that "rendered" is
  not "loaded".
- `no_log` is NOT needed here (no secret in the GET); keep it OFF so the failure
  status is visible in the log.

### 3.2 Pin the auth_oidc config schema (kills the schema-drift surface)

- Extract the v1.1.1 allowed top-level keys (`client_id`, `client_secret`,
  `discovery_url`, `display_name`, `features`, plus any v1.1.1 optional like
  `id_token_signing_alg`, `roles`, `claims` — **confirm against the
  hass-oidc-auth v1.1.1 `CONFIG_SCHEMA`/`__init__.py` before committing**) into
  `roles/pazny.homeassistant/vars/main.yml` as
  `homeassistant_auth_oidc_allowed_keys`, and the allowed `features.*` keys
  (`include_groups_scope`, `default_redirect`, …) as
  `homeassistant_auth_oidc_features_keys`.
- The `blockinfile` body stays human-authored (the `default_redirect` Jinja
  expression and `!secret` references make a fully data-driven render
  lower-signal). The gate parses the rendered block's keys and asserts every key
  ∈ the allowed list AND that the **removed v0.9 keys** (`automatic_user_linking`,
  `automatic_person_creation`) are ABSENT — the exact historical landmine, pinned
  explicitly so the failure message is self-documenting.

### 3.3 Smoke catalog entry (defence in depth, post-run)

Add to `state/smoke-catalog.yml` `smoke_endpoints`:

```yaml
- id: homeassistant-sso
  url: "http://127.0.0.1:{{ homeassistant_port | default(8123) }}/auth/oidc/welcome"
  expect: [200, 302]
  auth: "anon"
  when: "install_homeassistant | default(false) and install_authentik | default(false)"
  note: "HA auth_oidc provider endpoint — 404 means the config block failed CONFIG_SCHEMA (dead SSO)"
  tier: 1
```

Confirm the endpoint path matches §3.1. `auth: anon` because the welcome/redirect
route is reachable pre-session; if v1.1.1 gates it behind a session, fall back to
`expect`-NOT-404 semantics by asserting `[200, 302]` only (a 404 already fails).

---

## 4. Gates it needs (mandatory, offline, source-scan only)

### `tests/anatomy/test_homeassistant_sso_verify_loud.py`

Mirror `test_portainer_sso_verify_loud.py` shape (YAML-load `post.yml`, no
Docker / Authentik / live HA):

- A verify task exists that GETs the auth_oidc provider endpoint
  (`/auth/oidc/...`) — NOT `/` and NOT `/api/onboarding` (those never carry
  provider liveness; `/` is 200 even when `auth_oidc` was rejected).
- It declares `follow_redirects: none` and `status_code` includes the live set.
- It declares `failed_when` and it is **NOT** a bare `false`/`no`; the condition
  rejects the dead state (status not-live / 404).
- It is gated on `install_authentik`.
- A handler flush (`meta: flush_handlers`) OR a `wait_for_api` re-poll precedes
  the probe (so we don't verify the pre-restart state).
- The unverifiable / 404 path FAILS rather than soft-continuing (assert the
  verify is not a `debug`-only / `failed_when: false` task — that is precisely
  the soft bug shape this gate forbids).

### `tests/anatomy/test_homeassistant_auth_oidc_schema.py`

Pure source-scan over `roles/pazny.homeassistant/tasks/main.yml`:

- Locate the `# BEGIN ANSIBLE MANAGED - auth_oidc` … `# END …` blockinfile body
  in the `auth_oidc` injection task; extract the rendered top-level + `features.*`
  keys (tolerant scan — strip the Jinja `default_redirect` expression).
- Load `homeassistant_auth_oidc_allowed_keys` +
  `homeassistant_auth_oidc_features_keys` from
  `roles/pazny.homeassistant/vars/main.yml`.
- Assert every rendered key ∈ the allowed list (no unknown key → no
  `CONFIG_SCHEMA` rejection).
- Assert the removed v0.9 keys (`automatic_user_linking`,
  `automatic_person_creation`) are ABSENT from the block — the explicit,
  self-documenting landmine pin.
- Assert `discovery_url` references `{{ authentik_domain }}` and the
  `homeassistant` Authentik slug (catches the slug/domain drift surface), and
  that the secret keys (`oidc_client_id`/`oidc_client_secret`) match between the
  `!secret` references in the block and the `secrets.yaml` render task (catches
  the `!secret` mismatch surface).

Both gates are pure source-scan, run under the existing `pytest` job, need no
network, and keep the suite fast.

---

## 5. Risks

- **Exact endpoint path/case for hass-oidc-auth v1.1.1** —
  `/auth/oidc/welcome` vs `/auth/oidc/redirect` vs a `/auth/external/…`
  HA-core callback. Confirm against the plugin's registered routes at the pinned
  tag before writing the probe AND the smoke entry (wrong path → false RED). The
  live-vs-dead status contract (live 200/302, dead 404) must match what v1.1.1
  actually returns.
- **`meta: flush_handlers` side effects** — flushing re-runs ALL pending handlers
  in the play, not just `Restart homeassistant`; if other roles queued handlers
  by this point, scope carefully or prefer the `wait_for_api` re-poll. Verify the
  idempotence re-run stays `changed=0` (the macOS integration `changed=0` gate is
  load-bearing per CLAUDE.md).
- **Early-render vs post-bring-up fail asymmetry** — `main.yml`'s component WARN
  is deliberately NON-fatal (runs before stack bring-up; a hard fail there blocks
  downstream post-wiring incl. Gitea SSO). The new `post.yml` verify runs AFTER
  bring-up so a hard fail is safe. Do NOT "harmonise" them into both-fatal — keep
  the asymmetry and document why (one-line inline comment + this plan).
- **HA boots slowly / restart-loop on fresh DB** — known upstream (CLAUDE.md tech
  debt). The verify re-polls `/` first; the `wait_for_api` retries/delay must be
  generous enough that a cold first boot doesn't false-RED. Reuse the existing
  `_ha_ready` budget (20×10s) shape.
- **`default_redirect: true` + anon smoke** — when autologin is on, the welcome
  endpoint may 302 immediately; `expect: [200, 302]` already covers it. If anon
  is bounced to a login the runner can't follow, the entry still passes on 302
  (the redirect itself proves the route is registered — the opposite of 404).
- **`auth_oidc` plugin is community / pinned** — v1.1.1 schema is tied to THIS
  tag; the allowed-keys list must be re-derived on any
  `homeassistant_auth_oidc_version` bump. Document that coupling in
  `vars/main.yml` (mirrors the dead-pin history already in `main.yml`).

---

## 6. Verification recipe (no live mutation; READ-ONLY on any running system)

Offline / repo gates (the load-bearing proof):

```bash
# new + neighbouring SSO-verify gates green
python3 -m pytest tests/anatomy/test_homeassistant_sso_verify_loud.py \
                  tests/anatomy/test_homeassistant_auth_oidc_schema.py \
                  tests/anatomy/test_portainer_sso_verify_loud.py \
                  tests/anatomy/test_wordpress_oidc_install_verified.py \
                  tests/anatomy/test_sso_doctrine.py -q

# full anatomy suite stays green
python3 -m pytest tests/anatomy -q

# stock-Jinja trap (vars/main.yml is a role default, but run it per the hard rule)
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q

# playbook still parses
ansible-playbook main.yml --syntax-check
```

Negative-control (proves each gate actually bites; do NOT commit the breakage):

```bash
# 1. schema gate: temporarily add `automatic_user_linking: true` under the
#    auth_oidc block in tasks/main.yml → test_homeassistant_auth_oidc_schema MUST
#    go RED; revert.
# 2. verify gate: temporarily swap the verify endpoint to `/` (the soft shape)
#    OR set its failed_when to false → test_homeassistant_sso_verify_loud MUST go
#    RED; revert.
```

Live READ-ONLY spot-check on a host that already ran the playbook (optional,
human-supervised — NOT part of the overnight run, NO writes):

```bash
# live provider → 200 / 302 to Authentik; dead (CONFIG_SCHEMA rejected) → 404
curl -sS -o /dev/null -w '%{http_code}\n' \
  "http://127.0.0.1:8123/auth/oidc/welcome"

# the component actually landed (already hardened, sanity only)
ls ~/homeassistant/custom_components/auth_oidc/manifest.json

# the rendered block carries no removed v0.9 keys
grep -nE 'automatic_user_linking|automatic_person_creation' \
  ~/homeassistant/configuration.yaml   # expect: no matches
```

No `blank=true`, no container/data deletes, no writes to the live system — the
fix lands as repo edits + gates and propagates through the playbook on the next
operator-run reconverge.

---

## 7. Commit shape (when implemented — lands on branch only, never pushed)

- `fix(homeassistant): loud OIDC verify + pin auth_oidc schema`
  - body bullets: tendon (`auth_oidc:` blockinfile render → silent
    `CONFIG_SCHEMA` reject), symptom (HA boots, smoke `/` 200, but no "Sign in
    with Authentik" provider — dead SSO exits 0), structural fix (post-restart
    `/auth/oidc/welcome` live verify + allowed-keys schema pin + smoke entry),
    gates (`test_homeassistant_sso_verify_loud`,
    `test_homeassistant_auth_oidc_schema`).
- Conventional Commits, subject ≤50 chars, ≤6 bullets, no Co-Authored-By, no
  `--author`. Commit lands on `feat/v0.7-overnight` only — never pushed.
