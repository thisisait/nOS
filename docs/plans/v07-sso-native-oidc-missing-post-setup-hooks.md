# Plan — native_oidc services missing a loud post-setup verify hook

Status: PLAN (not implemented)
Branch: `feat/v0.7-overnight`
Item: `v0.7 / sso / native-oidc-missing-post-setup-hooks`
Author context: nOS, AIT. SSO is mandatory (memory `sso-mandatory-never-local-form`).
Sibling plan: `docs/plans/v07-sso-nextcloud-oidc-provider-verify-ok.md` (same
silent-failure class, scoped to Nextcloud's hook). This plan covers the
file/API-driven `native_oidc` services that register an OIDC client but ship
**no loud post-setup verify + no anatomy gate** at all.

---

## 1. Problem / why

The "user_oidc silent-failure saga" (root-caused 2026-06-13) established a class:
service-side OIDC registration tasks carry `no_log: true` + `failed_when: false`
(they hold a client secret), so a CLI/payload drift fails **silently** — the
playbook reports success while SSO is dead and the native login form (which must
not exist per SSO-mandatory doctrine) still works.

That saga produced **loud verify + anatomy gate** pairs for three services:
- Gitea — `authentik_service_post.yml` re-lists the OAuth2 source, `failed_when:
  "'authentik' not in stdout"` (no gate yet, but loud).
- Portainer — `test_portainer_sso_verify_loud.py` pins a `/api/settings`
  `AuthenticationMethod` assertion.
- WordPress — `test_wordpress_oidc_install_verified.py` pins a `wp plugin
  is-active` verify + a mirrored plugin-hook step.

**The gap:** the remaining file/API-driven `native_oidc` services register their
OIDC client and then **stop** — no loud re-read, no gate. A silent registration
failure passes green:

| Service | mode | Registers OIDC via | Post-setup verify? | Anatomy gate? |
|---|---|---|---|---|
| **erpnext** | native_oidc | Frappe `Social Login Key` doctype, `bench execute frappe.client.insert` (`roles/pazny.erpnext/tasks/post.yml:173`, `failed_when: false` + `no_log`) | ❌ only a `debug` result msg | ❌ none |
| **superset** | native_oidc | `superset_config.py` OAUTH render (`roles/pazny.superset/tasks/main.yml:19`); `post.yml` runs db-upgrade/init/admin all `failed_when: false` | ❌ no runtime probe that OAUTH is live | ❌ none |
| **homeassistant** | native_oidc | downloads `auth_oidc` HACS component (`roles/pazny.homeassistant/tasks/main.yml`) | ✅ **loud non-fatal WARN** (`stat` + `debug`, lines 123–139) | ❌ **none** (verify exists in code, nothing pins it) |
| jellyfin | native_oidc (Tier-4, `supports:no`) | SSO-Auth.xml — **DEFERRED by design** (post.yml:160, v4 XML wipe bug) | n/a (button intentionally not injected) | out of scope |

So three concrete sub-gaps, each in the exact silent-failure class the saga
exists to prevent:

1. **erpnext** — the `Social Login Key` create is soft + `no_log`; if the
   `bench execute frappe.client.insert` payload drifts (Frappe doctype field
   rename, e.g. `social_login_provider`/`client_id_field_name`) or the backend
   413/417s, the key is never created, the "Login with Authentik" button is
   absent, and the converge is green. No verify, no gate.
2. **superset** — OAUTH lives entirely in a rendered config file; the `post.yml`
   never confirms the provider is actually wired (a Flask-AppBuilder import error
   in `superset_config.py` boots Superset with DB-auth only and the playbook
   never notices). No verify, no gate.
3. **homeassistant** — already does the right thing (loud WARN), but it is
   **ungated**: a future refactor that drops the WARN or makes the download
   `failed_when: false`-and-forget regresses silently. Peer services get gates;
   HA does not.

Per the overnight rules — "if you cannot gate it, it is a plan not a fix" — the
deliverable is, per service: (a) a loud post-setup verify where missing
(erpnext, superset), and (b) an anatomy gate pinning the loud shape for all
three (erpnext, superset, homeassistant).

---

## 2. Exact files / roles to touch

| File | Change |
|------|--------|
| `roles/pazny.erpnext/tasks/post.yml` | **ADD** a loud verify after the `Social Login Key result` debug (after line 213): re-list `Social Login Key` filtered to `provider_name=Authentik` via `bench execute frappe.client.get_list`, with `failed_when: "'Authentik' not in (stdout)"` (NO bare `false`). Gated on `install_authentik` + site-running (reuse `_erpnext_site_config` / `_erpnext_health` guards already in the block). `changed_when: false`, NOT `no_log` (the list output carries no secret — only provider name). |
| `tests/anatomy/test_erpnext_oidc_login_key_verified.py` | **NEW** gate (mirrors `test_wordpress_oidc_install_verified.py`). |
| `roles/pazny.superset/tasks/post.yml` | **ADD** a loud verify after the admin-create task: probe the running container for OAUTH being active — `docker compose -p data exec -T superset cat /app/pythonpath/superset_config.py` (or the mounted override path) and assert `AUTH_OAUTH` is present, OR (preferred, runtime-true) GET Superset's `/api/v1/security/login` provider list / `/login/` and assert the Authentik provider name appears. **Pick the runtime-truest probe that needs no secret** (see §3.2 — verify the exact reachable surface before authoring). `failed_when` references the provider/`AUTH_OAUTH` token and is NOT bare `false`. Gated on `install_authentik` + container-running. |
| `tests/anatomy/test_superset_oidc_config_verified.py` | **NEW** gate. |
| `tests/anatomy/test_homeassistant_oidc_verify_loud.py` | **NEW** gate — pins the EXISTING `roles/pazny.homeassistant/tasks/main.yml` loud WARN (no role code change unless the gate exposes a defect). |

**Explicitly NOT touched:**
- `roles/pazny.jellyfin/tasks/post.yml` — SSO button is **deferred by design**
  (documented: v4 OidConfig XML-wipe bug; `supports:no` Tier-4). Adding a verify
  for a provider we intentionally do not inject would assert a false contract.
  The plan records it as out-of-scope; no gate (gating "absent by design" risks
  pinning the wrong shape — leave the documented comment as the contract).
- `tasks/stacks/authentik_service_post.yml` — Gitea/Portainer/Nextcloud live
  there and are already loud (and separately gated / plan-covered). Out of scope.
- `default.config.yml` / `default.credentials.yml` — **no new vars.** The verify
  tasks use literals (`Authentik`, `AUTH_OAUTH`) + already-defined vars
  (`authentik_oidc_erpnext_client_id`, `erpnext_site_name`, `install_authentik`).
  The stock-Jinja vars trap (`test_config_stock_jinja_only.py`) is therefore
  **not engaged**. If review later wants `erpnext_oidc_provider_name` instead of
  the literal, it MUST use stock filters + a real default — but keep the literal
  (lower risk, version-robust).

---

## 3. Approach

The shape is identical across all three: a **read-only re-read of what the
register step wrote**, asserted LOUD (`failed_when` that actually fails), gated
on `install_authentik` + container/site running, `changed_when: false`, and
NOT `no_log` (the re-read output names the provider but carries no secret — so
the failure message is actually legible, unlike the secret-bearing register).

### 3.1 erpnext — re-list the Social Login Key (loud)

The `Check for existing Authentik Social Login Key` task (post.yml:162) already
does the exact re-list we need with `failed_when: false`. The fix is a SECOND,
post-create re-list that is LOUD:

```yaml
- name: "[pazny.erpnext Post] Verify Authentik Social Login Key is registered"
  ansible.builtin.shell: >
    {{ docker_bin }} compose -p b2b exec -T erpnext-backend
    bench --site {{ erpnext_site_name }}
    execute frappe.client.get_list
    --kwargs '{"doctype":"Social Login Key","filters":{"provider_name":"Authentik"}}'
    2>&1
  register: _erpnext_slk_verify
  changed_when: false
  failed_when: "'Authentik' not in (_erpnext_slk_verify.stdout | default(''))"
  when:
    - install_authentik | default(false)
    - _erpnext_site_config.stat.exists
    - _erpnext_health.status | default(0) in [200, 403, 417]
```

- Lives INSIDE the existing `block:` (post.yml:156) so it inherits the same
  guards; place it as the block's last task (after the `result` debug:213).
- Bare `frappe.client.get_list` filtered by `provider_name` is the **stable**
  surface (the `insert` payload fields are what drift) — so the verify stays
  green across Frappe doctype renames, exactly like Nextcloud's bare
  `occ user_oidc:provider` list is the version-robust loud gate.
- Not `no_log`: the list output is `[{"name": "Authentik"}]`-shaped, no secret.

### 3.2 superset — verify OAUTH is live (loud)

Superset's OAUTH is a rendered config file, so the failure modes are: (a) the
file didn't mount, (b) `superset_config.py` raised on import and Superset fell
back to DB-auth. **Verify the runtime-truest reachable surface that needs no
secret** — author against whichever of these the live container exposes (check
in this order, READ-ONLY, before writing the task):

1. **Preferred (runtime-true):** GET the unauthenticated provider list. Superset
   (FAB) exposes the configured OAUTH providers on the login page; probe
   `http://127.0.0.1:{{ superset_port }}/login/` (or the FAB
   `/api/v1/security/...` provider surface if present in this version) and assert
   the Authentik provider name / "Sign in with Authentik" string appears. This
   proves `superset_config.py` imported cleanly AND OAUTH is the auth type.
2. **Fallback (config-true):** `docker compose -p data exec -T superset python -c
   "import superset_config as c; assert c.AUTH_TYPE == c.AUTH_OAUTH; print([p['name'] for p in c.OAUTH_PROVIDERS])"`
   and assert the Authentik provider name is in stdout. This catches an import
   error in the config (the most likely silent failure) without hitting HTTP.

Whichever is chosen, the task carries `failed_when` referencing the provider
token (NOT bare `false`), `changed_when: false`, gated on `install_authentik` +
container-running. The gate in §4 asserts whatever shape ships — **the gate is
the contract, not this prose.** Read the live container's reachable surface
first (READ-ONLY) so the probe targets something that actually exists.

### 3.3 homeassistant — gate the existing loud WARN (no code change)

HA already does the right thing: `Verify auth_oidc component landed` (stat) +
`WARN loudly if auth_oidc did not install` (debug, gated on the stat being
absent). The deliverable is purely the **gate** that pins this shape so it can't
silently regress. No role edit (unless the gate exposes a defect — e.g. the WARN
being `debug` not `fail` is intentional per the header comment "NON-FATAL …
would block every downstream service's post-wiring", so the gate asserts a loud
WARN, NOT a hard fail; see Risks).

### 3.4 The anatomy gates (the actual deliverable)

All three gates are **source-scan only** (no Docker / Authentik / live service),
mirroring `test_wordpress_oidc_install_verified.py` + `test_portainer_sso_verify_loud.py`
(`REPO = parents[2]`, `yaml.safe_load`, `_tasks()` / `_shell()` helpers verbatim).

**`test_erpnext_oidc_login_key_verified.py`:**
1. A verify task exists in `roles/pazny.erpnext/tasks/post.yml` that runs
   `frappe.client.get_list` with `provider_name":"Authentik"` AND `2>&1`.
2. Its `failed_when` is NOT a bare `false`/`no` and references `Authentik` +
   `not in` (fails LOUD when the key is absent).
3. The CREATE task (`frappe.client.insert`) keeps `failed_when: false` +
   `no_log: true` (pins that the verify is a SEPARATE loud task — mirrors
   WordPress's `test_install_task_still_idempotent_failsafe`).
4. The verify is gated on `install_authentik` and is a probe
   (`changed_when: false`).

**`test_superset_oidc_config_verified.py`:**
5. A verify task exists in `roles/pazny.superset/tasks/post.yml` whose command
   references the chosen provider/`AUTH_OAUTH` token (per §3.2).
6. Its `failed_when` references that token and is NOT bare `false`.
7. The db-upgrade/init/admin tasks keep their `failed_when: false` (the verify is
   the SEPARATE loud gate, not those soft tasks).
8. Gated on `install_authentik` + container-running, `changed_when: false`.

**`test_homeassistant_oidc_verify_loud.py`:**
9. A `stat` task registers the presence of
   `custom_components/auth_oidc/manifest.json`.
10. A loud WARN `debug` task fires `when: not (…manifest stat exists)` AND is
    gated on `install_authentik` — i.e. the operator IS told when HA SSO didn't
    install. (Assert a loud WARN, NOT a hard `fail` — see Risks: HA verify is
    deliberately non-fatal to avoid blocking downstream post-wiring.)
11. The download task carries `until:`/retry (pins the "transient retry, loud at
    the end" doctrine in the role header) — assert the retry exists so a refactor
    can't drop both the retry AND the WARN.

---

## 4. Gates it needs (and how the suite stays green)

- **New (the deliverable):** `test_erpnext_oidc_login_key_verified.py`,
  `test_superset_oidc_config_verified.py`,
  `test_homeassistant_oidc_verify_loud.py`.
- **Must stay green (unchanged):**
  - `test_portainer_sso_verify_loud.py`, `test_wordpress_oidc_install_verified.py`
    (peer precedents — untouched).
  - `test_sso_doctrine.py` — erpnext/superset/homeassistant are all `native_oidc`,
    unchanged.
  - `test_autologin_only_for_native_oidc_services.py`,
    `test_native_oidc_no_authentik_middleware.py` — no mode/middleware change.
  - `test_plugin_wiring_contract.py` — no plugin manifest block touched, but run
    it (post.yml edits must not perturb the wiring report).
- **Full suite + syntax:** `python3 -m pytest tests/anatomy/ -q` green AND
  `ansible-playbook main.yml --syntax-check` clean (new tasks are real task-file
  edits, so syntax-check genuinely exercises them — unlike a pure hook-data edit).

---

## 5. Risks

| Risk | Mitigation |
|------|-----------|
| **erpnext backend not reachable at verify time.** ERPNext's first-blank migration is flaky (CLAUDE.md known-debt; `erpnext_post.yml` auto-retries). A hard verify could fail a converge where the key WILL register on the retry. | Gate the verify on the SAME `_erpnext_health.status in [200,403,417]` guard the create already uses — if the backend isn't up, the whole block (create + verify) is skipped together, so the verify never fires without the create having had its chance. The verify is loud only when the site is reachable AND the key is genuinely absent. |
| **superset probe targets a surface that doesn't exist in this version.** FAB's provider-list endpoint differs across Superset versions. | §3.2: READ-ONLY-inspect the live container's reachable surface FIRST; prefer the `python -c "import superset_config"` fallback (version-stable) if the HTTP surface is uncertain. The gate asserts whatever ships. |
| **HA verify is non-fatal by design — a gate might wrongly demand a hard `fail`.** The role header explicitly keeps it a WARN so a dead HACS tag doesn't block every downstream service's post-wiring (incl. Gitea SSO). | The gate asserts a **loud WARN** (`debug` gated on absence + `install_authentik`), NOT `ansible.builtin.fail`. Pinning the WARN shape is the contract; do not "upgrade" it to fatal. |
| **Double-list noise (erpnext).** The block already lists the key once (idempotence check) and now lists again (verify). | Acceptable — both are read-only `frappe.client.get_list`, idempotent, no `notify`. Same dual-read shape Nextcloud's hook/role already carries. |
| **False sense the live system is fixed.** Repo-only; does NOT prove the operator's live erpnext/superset/HA SSO works tonight. | Out of scope by the overnight READ-ONLY rule. §6 is read-only live inspection + the source-scan gates; no live mutation. |
| **Frappe/FAB token drift breaks the verify literal.** | Verify uses the STABLE surface (bare `get_list` filtered by `provider_name`; `import superset_config`), not the drift-prone register payload — same reasoning that makes Nextcloud's bare `occ … :provider` list the robust gate. |

---

## 6. Verification recipe

### 6.1 Repo gates (the deliverable — must pass)
```bash
cd /Users/pazny/projects/nOS
python3 -m pytest tests/anatomy/test_erpnext_oidc_login_key_verified.py \
                  tests/anatomy/test_superset_oidc_config_verified.py \
                  tests/anatomy/test_homeassistant_oidc_verify_loud.py -q
python3 -m pytest tests/anatomy/ -q          # full suite stays green
ansible-playbook main.yml --syntax-check     # clean
```

### 6.2 Confirm the verify tasks landed where expected
```bash
python3 - <<'PY'
import yaml, pathlib
for path, needle in [
  ("roles/pazny.erpnext/tasks/post.yml", "provider_name\":\"Authentik"),
  ("roles/pazny.superset/tasks/post.yml", "AUTH_OAUTH"),
]:
    doc = yaml.safe_load(pathlib.Path(path).read_text())
    fws = [t.get("failed_when") for t in doc
           if isinstance(t, dict) and "Verify" in str(t.get("name",""))]
    assert any(fw not in (False, "false", None) for fw in fws), (path, fws)
    print("OK loud verify in", path)
PY
```

### 6.3 LIVE READ-ONLY spot-checks (optional, non-mutating)
```bash
# erpnext — list the Social Login Key (read-only; no insert/update)
docker compose -p b2b exec -T erpnext-backend \
  bench --site <site> execute frappe.client.get_list \
  --kwargs '{"doctype":"Social Login Key","filters":{"provider_name":"Authentik"}}'
# Expect a row naming Authentik.

# superset — prove the OAUTH config imports + lists the provider (read-only)
docker compose -p data exec -T superset python -c \
  "import superset_config as c; print(c.AUTH_TYPE==c.AUTH_OAUTH, [p['name'] for p in c.OAUTH_PROVIDERS])"
# Expect: True [..., 'authentik' / 'Authentik', ...]

# homeassistant — confirm the HACS component is present (read-only)
ls <homeassistant_config_dir>/custom_components/auth_oidc/manifest.json
```
If any is absent on the live box, that is a live-data finding to **report** to
the operator — NOT something this overnight run may fix (no live mutation).

---

## 7. Commit

Plan doc commits first (this file), then ONE fix commit on `feat/v0.7-overnight`:
```
fix(sso): loud post-setup verify for erpnext/superset SSO

- erpnext Social Login Key was created no_log+soft then never
  re-read; add a bare get_list verify that fails loud if absent
- superset OAUTH lives only in a rendered config; add a runtime
  probe asserting AUTH_OAUTH imported + provider listed
- gate erpnext/superset verifies + pin HA's existing loud WARN
  (3 new anatomy gates; same silent-failure class as Nextcloud)
```
(Conventional Commits, subject ≤50 chars, surgeon-tone bullets ≤6, no
Co-Authored-By, no `--author`. Commit only — never push.)
