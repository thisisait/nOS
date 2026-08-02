# v0.7 — SSO "missing verify": Home Assistant `auth_oidc` runtime verify

**Status:** PLAN (do NOT implement from this doc; this is a review-ready spec)
**Branch:** `feat/v0.7-overnight`
**Class:** SSO completeness audit — "install present but provider dead" silent-failure family
**Sibling closures:** WordPress (`test_wordpress_oidc_install_verified.py`), Portainer
(`test_portainer_sso_verify_loud.py`), Nextcloud `user_oidc` (root-caused 2026-06-13)

---

## 1. Problem / why

Home Assistant has **no native OIDC** in core — only OAuth2. nOS wires true
native OIDC ("Sign in with Authentik") by installing the community HACS
component `auth_oidc` (`christiaangoossens/hass-oidc-auth`) into
`custom_components/auth_oidc/`, rendering `secrets.yaml` with the Authentik
client credentials, and injecting an `auth_oidc:` block into
`configuration.yaml`. This is `mode: native_oidc` per
`files/anatomy/plugins/homeassistant-base/plugin.yml`.

The role (`roles/pazny.homeassistant/tasks/main.yml`) was hardened on
2026-06-13 after the component **silently vanished for weeks** (a single 30s
`get_url` timeout dropped it; `configuration.yaml` still referenced
`auth_oidc`, so HA booted *without* the Authentik provider and nobody noticed —
a dead pin: `v0.9.0` 404'd). That fix added retries + a **filesystem stat
verify** ("WARN loudly if auth_oidc did not install").

**The remaining gap (this item): the existing verify is FILE-LEVEL only.** It
asserts `custom_components/auth_oidc/manifest.json` exists on disk. It does
**not** assert that Home Assistant actually **loaded** the component and
**registered the OIDC auth provider at runtime**. The exact failure class that
bit WordPress / Portainer / Nextcloud applies here verbatim:

- The component tarball can land on disk yet HA refuses to load it — e.g. the
  v1.1.x `CONFIG_SCHEMA` rejects an unknown key (the role comment already
  documents that `automatic_user_linking` / `automatic_person_creation` were
  removed and now make HA "refuse to load auth_oidc"), a `!secret` lookup fails,
  or the `discovery_url` to Authentik is unreachable at boot.
- In every such case the file-stat verify is **green**, the operator gets HA's
  **local login picker with no "Sign in with Authentik" entry**, and SSO is
  silently dead. The local username/password form still works, so nothing
  errors — exactly the Nextcloud `user_oidc` silent-failure signature.

There is **no runtime gate** today: `roles/pazny.homeassistant/tasks/post.yml`
waits for the API and runs onboarding, but never checks the provider list.
There is also **no plugin-loader `post_compose` hook** mirroring a verify
(`files/anatomy/plugins/homeassistant-base/` has only `plugin.yml` +
`templates/`, no `hooks/` dir), unlike `wordpress-base` and `nextcloud-base`
which both ship `hooks/post_compose.yml` with a mirrored verify step.

**Why now / why it matters:** HA is a Tier-3 household-facing service. A dead
SSO provider here means household members cannot use their Authentik identity
and fall back to a shared local account — a real RBAC + audit regression, and
exactly the doctrine `sso-mandatory-never-local-form` forbids.

---

## 2. The runtime verify signal (grounding)

HA exposes the registered auth providers **without authentication** via the
login-flow / providers surface:

- `GET http://127.0.0.1:{{ homeassistant_port }}/auth/providers`
  returns a JSON list of registered auth providers. With `auth_oidc` loaded,
  the list contains an entry whose `type` is the OIDC provider id
  (`"auth_oidc"`) / whose `name` is the configured `display_name`
  (`"Authentik"`). Without it, only `homeassistant` (local) appears.

This endpoint is the HA analogue of WordPress `wp plugin is-active` and
Portainer `GET /api/settings → AuthenticationMethod == 3`: a **runtime
assertion that the provider is live**, not a liveness probe and not a file stat.

> Implementer MUST confirm the exact JSON key/value on the pinned
> `homeassistant_auth_oidc_version` (1.1.1) against a live HA before wiring the
> `failed_when` literal — read-only `curl` on the running container, see §6.
> The plan pins the *shape* (provider list contains the OIDC entry); the exact
> token (`type == "auth_oidc"` vs a `name`/`display_name` match) is a one-line
> literal to confirm, not a design decision. If `/auth/providers` proves
> unstable across versions, the fallback signal is `POST /auth/login_flow`
> (the picker the frontend renders) — same "does the OIDC provider appear" test.

---

## 3. Files / roles to touch

| File | Change |
|------|--------|
| `roles/pazny.homeassistant/tasks/post.yml` | **ADD** a loud runtime verify task: GET `/auth/providers`, gated on `install_authentik` + `_ha_ready` reached, `changed_when: false`, `failed_when` asserts the OIDC provider is present. Keep it NON-FATAL-but-LOUD (see §5 risk) — match the role's existing "HA OIDC is one optional service, runs early, must not block downstream wiring" doctrine: a `debug` WARN + a registered fact, NOT a hard `fail`. |
| `files/anatomy/plugins/homeassistant-base/hooks/post_compose.yml` | **CREATE** (new `hooks/` dir) — mirror the verify as a loader `post_compose` step (`runner: http_get` or `docker_exec curl`), gated on `install_authentik`, no `accept_substring` escape hatch — matching the `wordpress-base`/`nextcloud-base` hook shape so the verify surfaces in the loader replay summary too. |
| `tests/anatomy/test_homeassistant_oidc_verify_loud.py` | **CREATE** — the gate (see §4). |
| `docs/native-sso-survey.md` | **UPDATE** the homeassistant row's note to cite the runtime verify (provider-list assertion), closing the audit row. Doc-only, no behaviour. |

**Explicitly NOT touched:**
- `roles/pazny.homeassistant/tasks/main.yml` — the file-stat verify + retries
  stay exactly as is (they catch the *download* failure; this item catches the
  *load* failure — orthogonal, both kept).
- `default.config.yml` / `default.credentials.yml` — **no new vars** (avoids the
  stock-Jinja trap entirely). The verify reads existing vars
  (`homeassistant_port`, `install_authentik`, `authentik_domain`).
- The `auth_oidc` version pin / install path — unchanged.

---

## 4. The gate (`tests/anatomy/test_homeassistant_oidc_verify_loud.py`)

Source-scan only (no Docker / Authentik / live HA), modeled 1:1 on
`test_wordpress_oidc_install_verified.py` + `test_portainer_sso_verify_loud.py`.
Loads `roles/pazny.homeassistant/tasks/post.yml` and the new hook with
`yaml.safe_load`. Assertions:

1. **`test_post_has_runtime_provider_verify`** — post.yml has a task whose
   `ansible.builtin.uri.url` contains `/auth/providers` (the runtime provider
   list), method `GET`. Pins that the verify hits the provider surface, NOT a
   bare `/` liveness probe (the Portainer `/api/system/status` anti-pattern).
2. **`test_verify_asserts_oidc_provider_present`** — that task's `failed_when`
   (or the WARN `debug` task's `when`, depending on the loud-not-fatal shape
   chosen in §5) references the OIDC provider token (`auth_oidc` /
   `Authentik`) AND is **not a bare `false`** — i.e. the check actually
   evaluates provider presence, not nothing.
3. **`test_verify_is_authentik_and_ready_gated`** — `when` includes
   `install_authentik` and `_ha_ready` (does not run on a Docker-less host or
   before HA is up). `changed_when` is `false` (a probe, not a change).
4. **`test_verify_independent_of_install_attempt`** — the verify `when` must
   NOT depend on `_ha_oidc_dl` / `_ha_oidc_final` success — it must run even
   when a *prior* masked install failure occurred (that is exactly when it is
   needed). Mirrors WordPress `test_verify_runs_even_when_install_skipped`.
5. **`test_filestat_verify_still_present`** — the main.yml file-stat verify
   (`_ha_oidc_final` / "WARN loudly") is untouched: the two verifies are
   distinct (download-landed vs provider-loaded). Guards against a future
   refactor collapsing them.
6. **`test_loader_hook_mirrors_verify`** — the new
   `homeassistant-base/hooks/post_compose.yml` exists, its sequence contains a
   step hitting `/auth/providers`, gated on `install_authentik`, with **no**
   `accept_substring_in_stdout` escape hatch (mirrors WordPress
   `test_hook_mirrors_verify_step`).

Run: `python3 -m pytest tests/anatomy/test_homeassistant_oidc_verify_loud.py -q`

---

## 5. Risks

- **Fatal-vs-loud tension (PRIMARY risk).** The role authors deliberately made
  HA OIDC failures **non-fatal**: HA renders early in the iiab stack and a hard
  `fail` here "would block every downstream service's post-wiring (incl. Gitea
  SSO)" (main.yml comment, lines 116–122). A naive `failed_when: provider_absent`
  would regress that. **Mitigation / decision:** keep the runtime verify
  **LOUD but NON-FATAL** — a `debug` WARN task (same shape as the existing
  "WARN loudly if auth_oidc did not install") plus a registered fact, NOT
  `ansible.builtin.fail`. The gate (§4 assertion 2) therefore asserts on the
  WARN `when` / a `failed_when: false` + asserting `debug` pair, not on a hard
  fail. This diverges from Portainer (which CAN hard-fail because it runs in the
  service-post phase, late). Document the divergence inline. *(If the operator
  later wants this fatal, it's a one-line `fail` swap gated behind a flag — out
  of scope here.)*
- **Endpoint stability** — `/auth/providers` JSON shape could differ across HA
  versions. Mitigated by §6 live confirmation against the pinned version + the
  documented `login_flow` fallback. The gate asserts on the *token presence in
  the failed_when/when expression*, so a token tweak is a one-line change that
  keeps the gate meaningful.
- **`no_log` leakage** — the provider list does NOT contain secrets (only
  provider type/name), so the verify does NOT need `no_log` (unlike the
  password-reconverge tasks). Confirm the registered `uri` result carries no
  client_secret before dropping `no_log`; default to `no_log: true` if unsure.
- **False green when HA is mid-restart** — the verify runs after `_ha_ready`,
  but HA reloads components asynchronously after the `notify: Restart`
  handler. Mitigation: the verify lives in post.yml which runs after the
  stack-up health-wait; add a small `retries`/`until` (e.g. 6×5s) so a
  provider that registers a few seconds post-boot isn't a false WARN.
- **Host-mode HA** (`homeassistant_privileged: true`, `network_mode: host`) —
  `127.0.0.1:{{ homeassistant_port }}` still reaches HA in both bridge and host
  mode, so the verify URL is mode-agnostic. No special-casing needed (confirm).

---

## 6. Verification recipe (read-only; live system stays untouched)

**A. Gate + suite + syntax (the mandatory green bar):**
```bash
python3 -m pytest tests/anatomy/test_homeassistant_oidc_verify_loud.py -q
python3 -m pytest tests/anatomy -q
ansible-playbook main.yml --syntax-check
```

**B. Confirm the runtime signal on the LIVE box (read-only curl — no mutation):**
```bash
# is HA up + is the provider list reachable?
docker ps --filter name=iiab-homeassistant --format '{{.Names}} {{.Status}}'
curl -s http://127.0.0.1:8123/auth/providers | python3 -m json.tool
#   EXPECT (auth_oidc loaded): a list element with the OIDC provider
#   (type "auth_oidc" / name "Authentik") alongside the local "homeassistant".
#   If ONLY {"type":"homeassistant",...} appears → provider dead → the new
#   verify would WARN (this is the bug this item closes, observed live).

# cross-check the component is on disk (the OLD, file-level signal):
docker compose -p iiab exec -T homeassistant \
  test -f /config/custom_components/auth_oidc/manifest.json && echo FILE-OK
```
Use the curl output to pin the **exact** `failed_when` token literal before
finalizing the role task (§2 note). This is the only step that touches the
live box and it is GET-only.

**C. Render-only dry check (no compose up):**
```bash
ansible-playbook main.yml --tags homeassistant --check --diff \
  -e install_homeassistant=true -e install_authentik=true 2>&1 | tail -40
# confirm the new verify task plans, gated, changed=0 on a steady-state box.
```

---

## 7. Out of scope (explicit)

- Making the verify **fatal** (deliberate non-fatal per role doctrine — §5).
- Pinning a newer `auth_oidc` version / changing the install path.
- Any Authentik blueprint / provider-side change (the Authentik OIDC client for
  HA is already wired via `homeassistant-base/plugin.yml` `authentik:` block
  and the tofu registry — unchanged here).
- SSO autologin behaviour (`default_redirect`) — already shipped, dormant.

---

## 8. Commit

Single commit on `feat/v0.7-overnight` (this plan doc only; the implementation
is a separate future commit):

```
docs(plan): HA auth_oidc runtime verify (v0.7 SSO)
```

Implementation commit (future, not in this PR) would be:
```
fix(homeassistant): loud runtime verify of auth_oidc provider

- file-stat verify is green even when HA refuses to LOAD auth_oidc
  (CONFIG_SCHEMA reject / dead discovery_url) → silent dead SSO
- post.yml GETs /auth/providers, WARNs loudly if OIDC provider absent
- loader post_compose hook mirrors the verify (replay summary)
- non-fatal by design: HA renders early, must not block Gitea SSO
- gate: test_homeassistant_oidc_verify_loud.py
```
