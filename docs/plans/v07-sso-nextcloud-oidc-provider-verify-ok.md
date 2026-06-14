# Plan — Nextcloud OIDC provider: pin the loud verify + mirror it into the plugin hook

Status: PLAN (not implemented)
Branch: `feat/v0.7-overnight`
Item: `v0.7 / sso / nextcloud-oidc-provider-verify-ok`
Author context: nOS, AIT. SSO is mandatory (memory `sso-mandatory-never-local-form`).

---

## 1. Problem / why

Nextcloud is the **origin** of the "user_oidc silent-failure saga" (root-caused
2026-06-13): the `occ user_oidc:provider …` register/reconverge tasks run
`no_log: true` + `failed_when: false` (they carry the client secret), so a
CLI-arg drift — e.g. the `--mapping-displayname` → `--mapping-display-name`
rename in user_oidc 8.x — failed **silently**. The playbook reported success
while SSO was dead, and the operator only noticed because the native Nextcloud
login form still worked (which it must not, per the SSO-mandatory doctrine).

That saga produced a **loud verify** for Portainer
(`test_portainer_sso_verify_loud.py`) and WordPress
(`test_wordpress_oidc_install_verified.py`). Nextcloud — the class's namesake —
has the loud verify task **in code** but **no anatomy gate**, and the **plugin
hook path is missing the verify step entirely**. Two concrete gaps:

1. **No gate on the imperative path.** `tasks/stacks/authentik_service_post.yml`
   lines 288–297 already runs a loud re-list (`occ user_oidc:provider`) with
   `failed_when: "'authentik' not in (_nc_oidc_verify.stdout | default(''))"`.
   Nothing pins this. A future refactor that re-adds `failed_when: false`, drops
   the task, or weakens the assertion would silently regress the exact saga the
   task exists to prevent. Both peer services (Portainer, WordPress) are gated;
   Nextcloud is not.

2. **Plugin-loader path has no verify (live divergence).**
   `files/anatomy/plugins/nextcloud-base/hooks/post_compose.yml` (the
   `replay_api_calls` path the plugin loader runs — see `plugin.yml`
   `lifecycle.post_compose.replay_api_calls`) ends at `reconverge_provider_secret`.
   Its own header claims it "Mirrors tasks/stacks/authentik_service_post.yml:103-184
   byte-for-byte" — but it stops **before** the loud verify. So on the
   plugin-driven path (the LIVE render path; the role/imperative task is the
   dual-safe transitional copy per `roles/pazny.nextcloud/tasks/post.yml`
   header), a silent OIDC-arg drift still passes. The WordPress gate already
   asserts the hook mirrors its verify step (`test_hook_mirrors_verify_step`);
   Nextcloud must reach the same bar.

This is a `verify-ok` item: the runtime behaviour is believed correct on the
imperative path, but it is **ungated** and the **plugin path diverges**. Per the
overnight rules, "if you cannot gate it, it is a plan not a fix" — so the deliverable
is (a) a structural mirror of the verify into the hook and (b) an anatomy gate
that pins both paths.

---

## 2. Exact files / roles to touch

| File | Change |
|------|--------|
| `files/anatomy/plugins/nextcloud-base/hooks/post_compose.yml` | **ADD** a final `verify_provider_registered` sequence step (Phase 4) that re-lists `occ user_oidc:provider` and asserts `authentik` is present, with NO `accept_substring_in_stdout` escape hatch. Update the header line count claim. |
| `tests/anatomy/test_nextcloud_oidc_provider_verify_loud.py` | **NEW** anatomy gate (mirrors `test_portainer_sso_verify_loud.py` + `test_wordpress_oidc_install_verified.py::test_hook_mirrors_verify_step`). |
| `files/anatomy/docs/plugin-wiring-capabilities.md` *(optional, doc-only)* | If the wiring contract enumerates per-plugin post_compose steps, note the new verify step. Verify first whether it tracks step lists; skip if not. |

**Explicitly NOT touched:**
- `tasks/stacks/authentik_service_post.yml` — the loud verify (288–297) is already
  correct. The gate pins it; no code change unless the gate exposes a real defect.
- `roles/pazny.nextcloud/tasks/post.yml` — the role DB/admin/trusted-domains/
  OnlyOffice reconvergence is out of scope. The role does **not** register the
  OIDC provider (that lives in `authentik_service_post.yml` + the plugin hook),
  so no verify belongs here.
- No `default.config.yml` / `default.credentials.yml` change → the stock-Jinja
  vars trap (`test_config_stock_jinja_only.py`) is not engaged. (If review later
  wants a `nextcloud_oidc_provider_name` var instead of the literal `authentik`,
  it MUST use stock filters + a real default — but the current literal is fine
  and lower-risk; keep the literal.)

---

## 3. Approach

### 3.1 Mirror the loud verify into the plugin hook (structural fix)

Append a Phase 4 step to the `sequence:` list in
`files/anatomy/plugins/nextcloud-base/hooks/post_compose.yml`, after
`reconverge_provider_secret`:

```yaml
  # Phase 4 — LOUD verify (mirrors authentik_service_post.yml verify; the
  # register/reconverge steps run secret-bearing + soft, so a CLI-arg drift
  # (user_oidc 8.x --mapping-display-name rename) would pass silently. Re-list
  # providers — no secret in output — and FAIL if authentik isn't registered.
  - id: verify_provider_registered
    when: "_nc_running.state == 'running'"
    runner: docker_exec
    container: nextcloud
    compose_project: iiab
    user: www-data
    cmd: php occ user_oidc:provider
    expect_substring_in_stdout: authentik   # loud — no accept_substring escape hatch
```

Notes:
- Use the loader's loud-assertion key. **Verify the exact key name first** by
  grepping the post-compose replay runner
  (`files/anatomy/library/` / the loader module) for how `accept_substring_in_stdout`
  is consumed and whether a *required*-substring assertion key exists
  (e.g. `expect_substring_in_stdout` / `require_substring`). If the runner has
  **no** "must-contain → fail" primitive, fall back to a `register:` +
  `when:`-guarded second step that the runner fails on, OR (lowest risk) leave
  the imperative-path verify as the sole loud gate and have the hook re-run the
  same list with `register: _nc_oidc_verify` and no `accept_substring` (so a
  non-zero rc surfaces). The gate in §4 must assert whatever shape is chosen —
  the gate is the contract, not the prose here.
- Do NOT add `notify:` — verify is a read-only probe, nothing to converge.
- This is the same "verify after secret-bearing soft tasks" shape WordPress's
  hook already carries (`test_hook_mirrors_verify_step`).

### 3.2 The anatomy gate (the actual deliverable)

`tests/anatomy/test_nextcloud_oidc_provider_verify_loud.py` — source-scan only
(no Docker / Authentik / live Nextcloud), mirroring the two precedent gates.
Assertions:

**Imperative path (`tasks/stacks/authentik_service_post.yml`):**
1. A verify task exists that runs `occ user_oidc:provider` (the re-list, no args).
2. Its `failed_when` is **not** a bare `false`/`no` and **references**
   `authentik` + `not in` (i.e. it fails LOUD when the provider is absent).
3. The register + reconverge tasks keep `no_log: true` + `failed_when: false`
   (pins that the verify is a SEPARATE loud task, mirroring WordPress's
   `test_install_task_still_idempotent_failsafe`).
4. The verify task is gated on `install_nextcloud` + container-running, and is a
   probe (`changed_when: false`).

**Plugin path (`files/anatomy/plugins/nextcloud-base/hooks/post_compose.yml`):**
5. The `sequence:` contains a step whose `cmd` is `php occ user_oidc:provider`
   (the bare re-list) used as a verify, positioned AFTER the
   `register_authentik_provider` / `reconverge_provider_secret` steps.
6. That step carries **no** `accept_substring_in_stdout` escape hatch and DOES
   carry the loud-assertion key chosen in §3.1.
7. It is gated on `_nc_running.state == 'running'`.

Implementation mirrors `_tasks()` / `yaml.safe_load` helpers from the two
precedent gates verbatim (same `REPO = parents[2]` rooting).

---

## 4. Gates it needs (and how the suite stays green)

- **New:** `tests/anatomy/test_nextcloud_oidc_provider_verify_loud.py` (above) —
  this IS the gate the item requires.
- **Must stay green (unchanged):**
  - `test_portainer_sso_verify_loud.py`, `test_wordpress_oidc_install_verified.py`
    (peer precedents — untouched).
  - `test_plugin_wiring_contract.py` — adding a sequence step to a hook must not
    break the wiring contract; run it.
  - `test_nextcloud_proxy_awareness.py`, `test_nextcloud_ipv6_disable.py`,
    `test_autologin_only_for_native_oidc_services.py`,
    `test_native_oidc_no_authentik_middleware.py` — Nextcloud-adjacent; confirm
    no collateral.
  - `test_sso_doctrine.py` — SSO trichotomy; Nextcloud is `native_oidc`, unchanged.
- **Full suite + syntax:** `python3 -m pytest tests/anatomy/ -q` green AND
  `ansible-playbook main.yml --syntax-check` clean (hook YAML is data, not a
  task file, but a malformed `post_compose.yml` can still break a loader import
  path that pytest exercises).

---

## 5. Risks

| Risk | Mitigation |
|------|-----------|
| **Loader lacks a "must-contain → fail" key.** The hook runner may only support `accept_substring_in_stdout` (success-substring), not a *required*-substring assertion. | §3.1 fallback: register + rc-driven fail, or keep the imperative verify as the sole loud gate and have the hook re-list (rc surfaces). The gate asserts whatever shape ships. **Read the runner source before writing the hook step.** |
| **Double-verify is noisy but harmless.** Both the imperative task and the hook will re-list providers on the live render path. | Acceptable — it's a read-only `occ` list, idempotent, no `notify`. The dual-safe transition already double-runs register/reconverge by design (role header). |
| **False sense the live system is fixed.** This is repo-only; it does NOT prove the operator's live Nextcloud SSO works tonight. | Out of scope by the overnight READ-ONLY rule. The verification recipe (§6) is read-only inspection of the live system + the source-scan gate; no live mutation. |
| **Hook header line-count claim drifts.** The header says "Mirrors …:103-184 byte-for-byte" — adding a step makes that stale. | Update the header comment to reflect the verify addition; do NOT claim byte-for-byte once a step is added. |
| **user_oidc subcommand name drift across versions.** `occ user_oidc:provider` (bare list) is the stable surface; the register flags are what drift. | The verify deliberately uses the **bare list** (no flags) so it's version-robust — that's why it's the loud gate and the flagged register stays soft. |

---

## 6. Verification recipe

### 6.1 Repo gates (the deliverable — must pass)
```bash
cd /Users/pazny/projects/nOS
python3 -m pytest tests/anatomy/test_nextcloud_oidc_provider_verify_loud.py -q
python3 -m pytest tests/anatomy/ -q          # full suite stays green
ansible-playbook main.yml --syntax-check     # clean
```

### 6.2 Confirm the hook YAML is well-formed + the step landed
```bash
python3 - <<'PY'
import yaml, pathlib
doc = yaml.safe_load(pathlib.Path(
  "files/anatomy/plugins/nextcloud-base/hooks/post_compose.yml").read_text())
ids = [s["id"] for s in doc["sequence"]]
assert "verify_provider_registered" in ids, ids
# verify it's positioned AFTER reconverge
assert ids.index("verify_provider_registered") > ids.index("reconverge_provider_secret")
print("hook OK:", ids)
PY
```

### 6.3 LIVE READ-ONLY spot-check (optional, non-mutating — only inspects)
Proves the running Nextcloud already has the provider; touches nothing:
```bash
# READ-ONLY: occ list, no set/reset. Safe under the overnight rules.
docker compose -p iiab exec -T -u www-data nextcloud php occ user_oidc:provider
# Expect a row containing: authentik
```
If `authentik` is absent on the live box, that is a live-data finding to report
to the operator — NOT something this overnight run may fix (no live mutation).

---

## 7. Commit

One commit on `feat/v0.7-overnight` (the plan doc commits separately, first):
```
fix(sso): pin Nextcloud OIDC loud verify + mirror to hook

- gate test_nextcloud_oidc_provider_verify_loud pins the
  authentik_service_post re-list fail-loud (saga namesake was ungated)
- plugin hook gained the Phase-4 verify step it was missing vs the
  imperative path (replay path could pass on a silent arg-drift)
- bare `occ user_oidc:provider` list = version-robust loud assertion
```
(Conventional Commits, subject ≤50 chars, surgeon-tone bullets, no
Co-Authored-By, no `--author`. Commit only — never push.)
