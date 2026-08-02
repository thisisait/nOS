# Plan — Jellyfin SSO: close the XML-config silent-failure gap

- Status: PLAN (not implemented)
- Branch: `feat/v0.7-overnight`
- Class: silent SSO failure (same family as the 2026-06-13 Nextcloud `user_oidc` /
  Portainer OAuth2 root-cause: render/POST returns 0, live login is dead)
- Service tier: Jellyfin — `supports:no` (Tier-4), `native_oidc` via the
  `9p4/jellyfin-plugin-sso` SERVER PLUGIN. Button-only at best, never autologin.

---

## 1. Problem / why

`roles/pazny.jellyfin/tasks/main.yml` renders the SSO provider config to
`{{ jellyfin_config_dir }}/plugins/configurations/SSO-Auth.xml`
(`templates/SSO-Auth.xml.j2`) host-side, then `notify: Restart jellyfin`. The
Ansible `template` task succeeds whenever the file is written — so **the playbook
reports OK regardless of whether the plugin actually loaded the provider.**

The failure mode is documented in the template's own header comment and in
`tasks/post.yml` (the "DEFERRED" SSO-button block) but **is not gated and not
verified at runtime**:

> The v4 plugin's `.NET XmlSerializer` is strict on element ORDER. On ANY schema
> mismatch the deserializer silently falls back to an empty dict, **overwrites
> `SSO-Auth.xml` with `<OidConfigs />` on its next save**, and every
> `/sso/OID/start/<provider>` login then 400s **"Provider does not exist"**.

So three independent silent-failure surfaces exist today:

1. **Field-order drift** — an edit to `SSO-Auth.xml.j2` that reorders an
   `OidConfig` element (or drops/adds one out of declaration order vs
   `PluginConfiguration.cs@v4.0.0.4`) renders a *valid-looking* XML that the
   plugin rejects. No test catches the drift; the comment is the only guard.
2. **Plugin-overwrite race** — even a correct file gets wiped if a stale
   `SSO-Auth_*` dir (wrong `targetAbi`) co-loads, or if the plugin re-saves
   before/around the config render. `main.yml` already removes stale dirs, but
   nothing re-asserts the file *after* the restart settles, and nothing verifies
   the provider is live.
3. **No live verify** — unlike Portainer (`/api/settings` → `AuthenticationMethod`,
   loud `failed_when`, pinned by `test_portainer_sso_verify_loud.py`) and the
   post-2026-06-13 Nextcloud verify, Jellyfin's `tasks/post.yml` does the Startup
   wizard + password reconverge but **never probes the SSO endpoint**. A dead
   provider exits 0.

Net: a future contributor reorders one XML element, the blank run is green, smoke
is green (no SSO entry), and the operator discovers SSO is dead only by clicking
the login button. This is exactly the class we just spent cycles root-causing
elsewhere — Jellyfin is the one still uncovered.

---

## 2. Exact files / roles to touch

Code (repo-only; live system stays READ-ONLY):

- `roles/pazny.jellyfin/tasks/post.yml`
  - Add a **loud live SSO verify** task block, gated on
    `install_authentik | default(false)` and `_jf_ready.status == 200`, run AFTER
    the restart handler has flushed (`meta: flush_handlers` before the probe, or
    place the verify after a short `wait_for_api` re-poll).
  - Add a **config-survival re-assert**: stat `SSO-Auth.xml`, detect the
    `<OidConfigs />` empty-wipe (grep for the self-closing form OR absence of the
    provider `<key><string>…`), and if wiped, re-render + restart ONCE, then
    re-probe. Fail loud if still wiped (do NOT silently leave it broken).
- `roles/pazny.jellyfin/templates/SSO-Auth.xml.j2`
  - No semantic change required, but add an explicit **machine-readable
    field-order manifest anchor** the gate can diff against (see §4 — the gate
    can read the template directly; a sidecar `vars/sso_oidconfig_order.yml`
    listing the canonical element order is cleaner than parsing comments).
- `roles/pazny.jellyfin/vars/main.yml` (NEW, optional but preferred)
  - `jellyfin_sso_oidconfig_field_order: [...]` — the canonical
    `PluginConfiguration.cs@v4.0.0.4` declaration order as a list. Single source
    of truth consumed by BOTH the template render (assert) AND the gate.
- `state/smoke-catalog.yml`
  - Add a Jellyfin SSO smoke entry probing the plugin endpoint
    (`/sso/OID/start/Authentik` or `/SSO/OID/Start/Authentik` — confirm exact
    case/path against v4.0.0.4) with `when: "install_jellyfin | default(false) and
    install_authentik | default(false)"`, expecting a non-400 (a live provider
    302-redirects to Authentik; a dead one 400s "Provider does not exist").

Tests (mandatory — a fix without a gate is a PLAN):

- `tests/anatomy/test_jellyfin_sso_xml_field_order.py` (NEW)
- `tests/anatomy/test_jellyfin_sso_verify_loud.py` (NEW)

Docs:

- Update `roles/pazny.jellyfin/tasks/post.yml` DEFERRED comment block to point at
  the new verify (it stops being "deferred" once a loud probe exists).

---

## 3. Approach

### 3.1 Pin the XML field order (kills surface #1 — the drift)

- Extract the canonical `OidConfig` child-element declaration order from
  `PluginConfiguration.cs@v4.0.0.4` into
  `roles/pazny.jellyfin/vars/main.yml` as `jellyfin_sso_oidconfig_field_order`
  (the exact 28-ish elements: `OidEndpoint, OidClientId, OidSecret, Enabled,
  EnableAuthorization, EnableAllFolders, EnabledFolders, AdminRoles, Roles,
  EnableFolderRoles, EnableLiveTvRoles, EnableLiveTv, EnableLiveTvManagement,
  LiveTvRoles, LiveTvManagementRoles, FolderRoleMappings, RoleClaim, OidScopes,
  DefaultProvider, SchemeOverride, PortOverride, NewPath, CanonicalLinks,
  DefaultUsernameClaim, DisableHttps, DoNotValidateEndpoints,
  DoNotValidateIssuerName`). Confirm the list against the upstream file at the
  pinned tag before committing.
- Template stays human-authored (the `{% for %}` loops over roles/scopes make a
  fully data-driven render awkward and lower-signal); the gate enforces that the
  template's element order MATCHES the vars list. This keeps the template
  readable while making any future reorder fail a fast offline test instead of a
  live login.

### 3.2 Loud live verify (kills surface #3 — the dead provider exits 0)

In `tasks/post.yml`, after the Startup/password flow and a handler flush:

- `meta: flush_handlers` so the `Restart jellyfin` handler actually runs before
  the probe (otherwise we verify the pre-restart state).
- Re-poll `/health` (reuse `pazny._common_tasks wait_for_api.yml`) so we don't
  probe mid-restart.
- `ansible.builtin.uri` GET the plugin endpoint
  `http://127.0.0.1:{{ jellyfin_port }}/sso/OID/start/{{ jellyfin_oidc_provider_name }}`
  with `status_code: [200, 302]` and `follow_redirects: none`.
  - A LIVE provider issues a 302 to Authentik's `/application/o/authorize/…`.
  - A DEAD/wiped provider returns 400 with body "Provider does not exist".
- `failed_when:` asserts the status is in the live set AND (defensively) the body
  does NOT contain "Provider does not exist". NOT a bare `false`. Gate on
  `install_authentik | default(false)`.
- Mirror the Portainer pattern: an unverifiable probe (endpoint unreachable / 0)
  must FAIL, not soft-skip, when `install_authentik` is on.

### 3.3 Config-survival re-assert (mitigates surface #2 — the wipe race)

Before the verify (or as the remediation when verify trips once):

- `stat` + `slurp` `SSO-Auth.xml`; detect the empty-wipe signature
  (`<OidConfigs />` self-closing OR the provider `<string>{{ name }}</string>`
  key missing).
- If wiped: re-render the template, restart, `wait_for_api`, then run the verify.
  Do this AT MOST once (a `_jf_sso_reasserted` guard var) to avoid a restart loop.
- If still wiped/dead after the single re-assert → `ansible.builtin.fail` with the
  "Provider does not exist — schema drift, see SSO-Auth.xml.j2 header" message.

This keeps the run idempotent: steady-state the file already matches, stat shows
the provider present, verify 302s, zero changes.

### 3.4 Smoke catalog entry (defence in depth, post-run)

Layer a Jellyfin SSO entry in `state/smoke-catalog.yml` so `tools/nos-smoke.py`
also catches a regression on any later reconverge (not just the role run). Use
`auth: anon`, `expect: [302]` (live provider redirects to Authentik), gated
`when: install_jellyfin … and install_authentik …`.

---

## 4. Gates it needs (mandatory, offline, source-scan only)

### `tests/anatomy/test_jellyfin_sso_xml_field_order.py`

- Parse `roles/pazny.jellyfin/templates/SSO-Auth.xml.j2` with a tolerant scan
  (strip Jinja `{# #}` / `{% %}`; extract the ordered list of `<Tag>` opening
  elements INSIDE the single `<OidConfig>` block).
- Load `jellyfin_sso_oidconfig_field_order` from
  `roles/pazny.jellyfin/vars/main.yml`.
- `assert template_order == vars_order` — exact sequence match. This is the
  single test that would have caught the historical `PortOverride`-position drift.
- Second assertion: the `<OidConfigs>` block contains exactly one provider `<key>`
  whose `<string>` equals `{{ jellyfin_oidc_provider_name }}` (no accidental
  empty `<OidConfigs />`).
- Third assertion: `SchemeOverride` is immediately followed by `PortOverride`
  then `NewPath` (the exact historical landmine, pinned explicitly so the failure
  message is self-documenting).

### `tests/anatomy/test_jellyfin_sso_verify_loud.py`

Mirror `test_portainer_sso_verify_loud.py` shape (YAML-load `post.yml`, no
Docker/Authentik):

- The verify task GETs the `/sso/OID/start/<provider>` endpoint (NOT `/health`,
  NOT `/Startup/*` — those never carry provider liveness).
- It declares `failed_when` and it is NOT a bare `false`/`no`; the condition
  references the live status set AND/OR rejects "Provider does not exist".
- It is gated on `install_authentik`.
- A guard exists that FAILS (`ansible.builtin.fail`) on the unverifiable /
  still-wiped path rather than silently continuing (the re-assert ceiling).
- No remaining "verify" task uses `/health` or `/Startup/Configuration` as the
  SSO liveness proof (the soft-bug shape).

Both gates are pure source-scan, run under the existing `pytest` job, need no
network, and keep the suite fast.

---

## 5. Risks

- **Exact endpoint path/case for v4.0.0.4** — `/sso/OID/start/<provider>` vs
  `/SSO/OID/Start/<provider>`; confirm against the plugin's controller routes at
  the pinned tag before writing the probe (wrong path → false RED). The verify
  task's `status_code`/`follow_redirects` must match what v4 actually returns for
  a live provider (302 to Authentik) vs dead (400).
- **`meta: flush_handlers` placement** — flushing too early re-runs other pending
  handlers in the role; scope the flush carefully (or `wait_for_api`-poll instead
  of flushing). Verify the idempotence re-run stays `changed=0`.
- **Re-assert loop** — the single-shot `_jf_sso_reasserted` guard MUST prevent a
  restart loop; if the plugin wipes deterministically (genuine schema bug, not a
  race) the run should fail loud once, not thrash.
- **9p4 plugin is archived read-only** — v4.0.0.4 is end-of-line; Jellyfin 10.12
  will need a successor plugin. The field-order vars list is tied to THIS tag;
  document that a plugin bump must re-derive the order. (Pre-existing tech debt,
  not introduced here.)
- **Live verify is host-side localhost** — fine on macOS/Linux where the role
  runs; gated on `nos_docker_ready` upstream already, and on `_jf_ready`.
- **Smoke `expect: [302]`** assumes anon hits the provider redirect; if the
  endpoint requires a session, fall back to asserting NOT-400 only.

---

## 6. Verification recipe (no live mutation; READ-ONLY on any running system)

Offline / repo gates (the load-bearing proof):

```bash
# new + neighbouring gates green
python3 -m pytest tests/anatomy/test_jellyfin_sso_xml_field_order.py \
                  tests/anatomy/test_jellyfin_sso_verify_loud.py \
                  tests/anatomy/test_portainer_sso_verify_loud.py \
                  tests/anatomy/test_sso_doctrine.py -q

# full anatomy suite stays green
python3 -m pytest tests/anatomy -q

# playbook still parses
ansible-playbook main.yml --syntax-check

# stock-Jinja trap: any new var in default.* must pass (vars/main.yml is a role
# default, NOT a pre-core-up var, so it is out of the {{ vars }} eager-resolve
# namespace — but run the gate anyway to be safe)
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q
```

Negative-control (proves the field-order gate actually bites):

```bash
# temporarily swap PortOverride below NewPath in the template → field-order test
# MUST go RED; revert. (Do NOT commit the swap.)
```

Live READ-ONLY spot-check on a host that already ran the playbook (optional,
human-supervised — NOT part of the overnight run):

```bash
# live provider → 302 to Authentik; dead/wiped → 400 "Provider does not exist"
curl -sS -o /dev/null -w '%{http_code}\n' \
  "http://127.0.0.1:8096/sso/OID/start/Authentik"

# config survival: provider key still present, not an empty <OidConfigs />
grep -o '<OidConfigs[^>]*>' ~/jellyfin/config/plugins/configurations/SSO-Auth.xml
```

No `blank=true`, no container/data deletes, no writes to the live system — the
fix lands as repo edits + gates and propagates through the playbook on the next
operator-run reconverge.

---

## 7. Commit shape (when implemented — lands on branch only, never pushed)

- `fix(jellyfin): loud SSO verify + pin OidConfig XML order`
  - body bullets: tendon (SSO-Auth.xml render → silent plugin wipe), symptom
    ("Provider does not exist" 400 at login, run green), structural fix (live
    `/sso/OID/start` verify + field-order vars + single-shot re-assert), gates
    (`test_jellyfin_sso_xml_field_order`, `test_jellyfin_sso_verify_loud`).
- Conventional Commits, subject ≤50 chars, ≤6 bullets, no Co-Authored-By, no
  `--author`.
