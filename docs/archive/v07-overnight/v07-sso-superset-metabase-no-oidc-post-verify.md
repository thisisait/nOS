# Plan — Superset / Metabase "no autologin-able OIDC" ceilings: pin the classifications loud

Status: PLAN (not implemented)
Branch: `feat/v0.7-overnight`
Item: `v0.7 / sso / superset-metabase-no-oidc-post-verify`
Author context: nOS, AIT. SSO is mandatory (memory `sso-mandatory-never-local-form`);
autologin ceilings doctrine (memory `autologin-coverage-ceilings` + `sso-autologin-feature`).

---

## 1. Problem / why

This is a **`post-verify`** item: the runtime classification for both BI services
is believed correct, but the *reasons* they sit where they do are **ungated**, so a
plausible future refactor could silently regress SSO. Two distinct, documented
ceilings need to become enforced contracts, not just prose in
`docs/native-sso-survey.md` / `docs/sso-autologin-plan.md`.

The item title says "no-oidc". The precise, verified reality (read from the
plugin manifests + role templates, 2026-06-14) is **NOT** "neither has OIDC" —
it is "**neither has an OIDC path that can be auto-logged-in cleanly**":

- **Metabase = `forward_auth`, genuinely no OIDC.** Metabase **OSS** paywalls
  OAuth/SAML/JWT into the Pro/Enterprise tier (community issue
  [metabase#28195](https://github.com/metabase/metabase/issues/28195)).
  `roles/pazny.metabase/templates/compose.yml.j2` (49 lines) carries **zero**
  auth/oidc/oauth/jwt/saml env. The plugin is correctly `forward_auth` (pure
  access gate, shared operator account) and **declares no `autologin` block**
  (correct — pure-proxy services must not, per
  `test_no_autologin_for_pure_proxy_services`).
  **Ungated risk:** nothing pins *why* it is forward_auth. A future "add SSO to
  Metabase" change could flip `metabase-base/plugin.yml` to
  `mode: native_oidc` + add a `OAUTH_PROVIDERS`/`MB_*` env block — the manifest
  would pass `test_sso_doctrine.py` (native_oidc is a canonical mode) and the
  autologin gates (no autologin block present), but the **feature does not exist
  in the OSS image we ship**, so SSO would be dead while the manifest claims
  native OIDC. The classification's load-bearing fact (no OIDC env in the
  shipped OSS compose) is asserted nowhere.

- **Superset = `native_oidc`, but its autologin is honestly *partial*.**
  `roles/pazny.superset/templates/superset_config.py.j2` (91 lines) DOES wire
  real Flask-AppBuilder `OAUTH_PROVIDERS` against Authentik (lines 58–68) — so
  Superset has working app-level OIDC ("Sign in with Authentik" button). What it
  **cannot** do is hide the local `/login` form: the only autologin lever is
  `OAUTH_SKIP_PROVIDER_SELECTION` (lines 87–90), which merely auto-picks the
  single OAuth provider — the username/password form still exists. And the flag
  is **version-unverified** (`supports: partial`, landed after `6.0.0`; the pin
  is `apache/superset:6.0.0-dev`, exact min-version unconfirmed). The plugin
  block already encodes this honestly: `autologin.supports: "partial"`,
  `autologin.hides_local_form: false`, `break_glass: "flag=False"`.
  **Ungated risk:** nothing pins that this stays honest. A future commit could
  set `hides_local_form: true` (false — the form survives) or `supports: "yes"`
  (over-promising a version-gated flag), or the role template's else-branch
  (`OAUTH_SKIP_PROVIDER_SELECTION = False`, line 90) could be dropped so the
  flag is emitted unconditionally on an image that doesn't support it. Each
  would degrade the operator's mental model of what SSO actually does here.

Per the overnight rules — "if you cannot gate it, it is a plan not a fix" — the
deliverable is **one anatomy gate** (source-scan only, no Docker / no live
mutation) that pins both ceilings so the documented reality can't silently rot.
No behaviour change ships: both services are already classified correctly and
verified healthy live (`data-superset-1`, `data-metabase-1` both `Up … healthy`
at write time). This item adds the **missing contract**, nothing more.

---

## 2. Exact files / roles to touch

| File | Change |
|------|--------|
| `tests/anatomy/test_bi_sso_ceilings.py` | **NEW** anatomy gate. Source-scan only (yaml.safe_load on plugin manifests + read role templates as text). Pins: (a) Metabase forward_auth ⇔ no-OIDC-env rationale; (b) Superset native_oidc autologin honesty. No Docker, no network. |
| `files/anatomy/plugins/metabase-base/plugin.yml` *(comment-only, optional)* | Add a one-line `# CEILING-PIN:` breadcrumb above the `authentik:` block pointing at the new gate + issue #28195, so the next editor sees the constraint before flipping the mode. **No semantic change.** |
| `files/anatomy/plugins/superset-base/plugin.yml` *(comment-only, optional)* | Same breadcrumb above the `autologin:` block. **No semantic change.** |

**Explicitly NOT touched:**
- `roles/pazny.metabase/templates/compose.yml.j2` — correct as-is (no OIDC env;
  that is the *fact* the gate pins, not a defect to fix).
- `roles/pazny.superset/templates/superset_config.py.j2` — the OAUTH_PROVIDERS
  wiring + the `{% if … %}…{% else %}OAUTH_SKIP_PROVIDER_SELECTION = False{% endif %}`
  gating is correct and honest. The gate pins it; no code change unless the gate
  exposes a real defect.
- `metabase-base/plugin.yml` / `superset-base/plugin.yml` **`authentik` semantics**
  — modes, client_ids, autologin fields are all correct. Only optional
  comment breadcrumbs (above) are in scope.
- `default.config.yml` / `default.credentials.yml` — **no new var.** The
  stock-Jinja vars trap (`test_config_stock_jinja_only.py`) is therefore **not
  engaged**. (If a reviewer later wants service names as vars, any new var MUST
  use stock filters + a real default — but the gate hard-codes the two service
  names, which is lower-risk and sufficient.)
- `docs/native-sso-survey.md` / `docs/sso-autologin-plan.md` — already correct;
  they are the *source* the gate enforces, not something to edit.

---

## 3. Approach

### 3.1 The anatomy gate (the actual deliverable)

`tests/anatomy/test_bi_sso_ceilings.py` — pure source-scan, mirrors the helper
shape of `test_sso_doctrine.py` / `test_autologin_only_for_native_oidc_services.py`
(`REPO = pathlib.Path(__file__).resolve().parents[2]`, `yaml.safe_load`). Four
assertions, two per service. Each asserts BOTH halves of a ceiling — the
classification AND its load-bearing reason — so the gate fails if either drifts.

**Metabase (forward_auth ⇔ no OIDC in the OSS image):**

1. `test_metabase_is_forward_auth_not_oidc`
   - `metabase-base/plugin.yml` `authentik.mode` (or `.provider_type`) ==
     `forward_auth`. If this ever reads `native_oidc`/`header_oidc`, fail with a
     message naming issue #28195 ("Metabase OSS has no OIDC; do not reclassify
     without bumping to a Pro image + wiring real env").
   - The plugin declares **no** `autologin` block (belt-and-suspenders with
     `test_no_autologin_for_pure_proxy_services`; kept local so the failure
     message ties to the BI ceiling).

2. `test_metabase_compose_has_no_oidc_env`
   - Read `roles/pazny.metabase/templates/compose.yml.j2` as text; assert it
     contains **none** of the auth-flip tokens that would indicate someone
     wired OIDC: case-insensitive search for `MB_JWT`, `MB_SAML`,
     `OAUTH`, `OIDC`, `SSO_` (Metabase's enterprise auth env all start `MB_`).
     This is the *fact* that justifies the forward_auth classification — if a
     future change adds OIDC env to the OSS image, this fails LOUD and forces the
     editor to (a) confirm a Pro image and (b) update assertion #1 deliberately.
   - **Token list is allow-list-reviewed in the gate's docstring** so the next
     author understands what "no OIDC env" means precisely (avoid false-positive
     on an unrelated `MB_` var — scope the match to auth-flavoured substrings,
     not all of `MB_`).

**Superset (native_oidc, honest partial autologin):**

3. `test_superset_is_native_oidc_with_real_oauth_providers`
   - `superset-base/plugin.yml` `authentik.mode` == `native_oidc`.
   - `roles/pazny.superset/templates/superset_config.py.j2` text contains
     `AUTH_TYPE = AUTH_OAUTH` **and** `OAUTH_PROVIDERS` **and**
     `"name": "authentik"` — i.e. the native OIDC wiring is really present
     (guards against a silent downgrade to forward_auth that would orphan the
     OAUTH_PROVIDERS render path).

4. `test_superset_autologin_is_honestly_partial`
   - In `superset-base/plugin.yml` `authentik.autologin`:
     `supports == "partial"` (NOT `"yes"` — the flag is version-unverified) AND
     `hides_local_form` is **falsey** (the local `/login` form survives
     `OAUTH_SKIP_PROVIDER_SELECTION`) AND a `break_glass` string is present.
   - In `superset_config.py.j2`: the `OAUTH_SKIP_PROVIDER_SELECTION = True`
     emission is **gated behind a Jinja `{% if … %}`** (i.e. `{% if` appears
     before the `= True` line) AND the file also contains the
     `OAUTH_SKIP_PROVIDER_SELECTION = False` default (the else-branch). This
     pins that the version-gated flag is never emitted unconditionally — an
     unsupported image must default to provider-selection, not auto-skip.

All four are read-only string/YAML assertions; the gate runs offline in
milliseconds and never touches the live system.

### 3.2 Optional comment breadcrumbs (defence-in-depth, no semantics)

Above the relevant block in each plugin manifest, a single `# CEILING-PIN:` line
naming `tests/anatomy/test_bi_sso_ceilings.py` (+ #28195 for Metabase). This is
purely so an editor sees the constraint at the edit site, not only when CI goes
red. If review prefers zero manifest churn, drop this — the gate alone is the
contract. (Comment lines do not change `yaml.safe_load` output, so existing
plugin gates are unaffected.)

---

## 4. Gates it needs (and how the suite stays green)

- **New:** `tests/anatomy/test_bi_sso_ceilings.py` (above) — this IS the gate the
  item requires.
- **Must stay green (unchanged), confirm no collateral:**
  - `test_sso_doctrine.py` — canonical-mode + naming. Metabase stays
    forward_auth, Superset stays native_oidc; unchanged.
  - `test_autologin_only_for_native_oidc_services.py` /
    `test_no_autologin_for_pure_proxy_services.py` — the new gate is the
    BI-specific *reason* layer beneath these mechanism gates; it must not
    contradict them (Metabase has no autologin block; Superset's autologin is on
    a native_oidc service). Run both.
  - `test_autologin_block_has_required_fields.py`,
    `test_autologin_no_means_no.py`, `test_each_autologin_plugin_renders_correct_env.py`,
    `test_autologin_config_var_resolves.py` — Superset's autologin block is
    touched only by comment (if at all); confirm still green.
  - `test_plugin_wiring_contract.py` — no manifest block added/removed (only an
    optional comment); run it to be sure.
  - `test_config_stock_jinja_only.py` — **not engaged** (no new var) but run the
    full suite anyway.
- **Full suite + syntax:**
  ```bash
  python3 -m pytest tests/anatomy/ -q          # full suite stays green
  ansible-playbook main.yml --syntax-check     # clean
  ```
  (The change is test-only + at most YAML comments; syntax-check is a guard
  against an accidental manifest typo, not a primary risk.)

---

## 5. Risks

| Risk | Mitigation |
|------|-----------|
| **Over-broad OIDC-env token match on Metabase.** Matching bare `MB_` or `AUTH` could false-positive on an innocent future env (e.g. `MB_DB_*`, an unrelated `AUTH`-substring). | Scope the deny-list to auth-flip substrings only: `MB_JWT`, `MB_SAML`, `OAUTH`, `OIDC`, `SSO_`. Document the list + intent in the gate docstring so the next editor extends it deliberately. Verify against the current 49-line compose (it has none) before committing. |
| **Superset min-version becomes confirmed later** (the flag is provably in the pinned image). | The gate asserts `supports == "partial"`, not `== "no"`. When the version is pinned-and-confirmed, flipping to `"yes"` is a deliberate one-line gate edit + a survey-doc update — exactly the auditable change we want. Until then, "partial" is the honest contract. |
| **`hides_local_form` is the load-bearing honesty bit.** If Superset ever *does* hide the form (e.g. via a reverse-proxy rule), the gate would wrongly fail. | That would be a real doctrine change (forward_auth-style form suppression on a native_oidc service) and SHOULD require a deliberate gate edit. The current shipped reality is `hides_local_form: false`; pin it. |
| **False sense the live system is fixed.** This is repo-only; it does not change tonight's live SSO. | By design — both services are already correct and verified `healthy` live. This item adds the missing *contract*; the live read-only spot-check (§6.3) confirms reality matches, mutating nothing. |
| **Comment breadcrumb churn** if review wants zero manifest edits. | Breadcrumbs are explicitly optional (§3.2); the gate is the deliverable. Drop them on request. |
| **Item title vs. reality mismatch** ("no-oidc" — but Superset *has* OIDC). | Plan §1 reconciles this explicitly: the shared ceiling is "no clean autologin-able OIDC path", not "no OIDC". The gate pins the *actual* per-service reality, not the title's shorthand. |

---

## 6. Verification recipe

### 6.1 Repo gates (the deliverable — must pass)
```bash
cd /Users/pazny/projects/nOS
python3 -m pytest tests/anatomy/test_bi_sso_ceilings.py -q
python3 -m pytest tests/anatomy/ -q          # full suite stays green
ansible-playbook main.yml --syntax-check     # clean
```

### 6.2 Confirm the manifests/templates the gate reads still say what the plan claims
```bash
python3 - <<'PY'
import yaml, pathlib
P = pathlib.Path("files/anatomy/plugins")
mb = yaml.safe_load((P/"metabase-base/plugin.yml").read_text())["authentik"]
sp = yaml.safe_load((P/"superset-base/plugin.yml").read_text())["authentik"]
assert mb["mode"] == "forward_auth", mb["mode"]
assert "autologin" not in mb, "metabase must NOT carry an autologin block"
assert sp["mode"] == "native_oidc", sp["mode"]
assert sp["autologin"]["supports"] == "partial", sp["autologin"]["supports"]
assert sp["autologin"]["hides_local_form"] is False, sp["autologin"]
mb_compose = pathlib.Path(
  "roles/pazny.metabase/templates/compose.yml.j2").read_text().lower()
assert not any(t in mb_compose for t in ("mb_jwt","mb_saml","oauth","oidc")), \
  "metabase OSS compose unexpectedly carries OIDC/OAuth env"
sp_cfg = pathlib.Path(
  "roles/pazny.superset/templates/superset_config.py.j2").read_text()
assert "AUTH_TYPE = AUTH_OAUTH" in sp_cfg and "OAUTH_PROVIDERS" in sp_cfg
assert "OAUTH_SKIP_PROVIDER_SELECTION = False" in sp_cfg  # honest else-branch
print("manifests/templates match plan")
PY
```

### 6.3 LIVE READ-ONLY spot-check (optional, non-mutating — only inspects)
Both containers are up (`data-superset-1`, `data-metabase-1`). These read only;
they touch nothing. Safe under the overnight READ-ONLY rule.
```bash
# Superset: confirm the native OAuth provider is actually configured (read-only).
docker exec -i data-superset-1 sh -c \
  'grep -c "authentik" /app/pythonpath/superset_config.py' 2>/dev/null \
  || echo "superset_config path differs — inspect via: docker exec data-superset-1 env | grep -i SUPERSET_CONFIG_PATH"
# Expect a non-zero count (the authentik OAUTH_PROVIDERS block is present).

# Metabase: confirm the OSS image exposes NO OIDC/SSO settings (read-only API GET).
# /api/session/properties is public-readable; OSS returns no enterprise SSO keys.
docker exec -i data-metabase-1 sh -c \
  'curl -s http://localhost:3000/api/session/properties | grep -o "\"[a-z-]*sso[a-z-]*\"" | sort -u' \
  2>/dev/null || echo "metabase props probe skipped"
# Expect: no jwt-enabled / saml-enabled = true (OSS) — confirms forward_auth is the only gate.
```
If the live state contradicts the gate (e.g. Metabase suddenly exposes enabled
SSO settings, or Superset's config lacks the authentik provider), that is a
**live-data finding to report to the operator** — NOT something this overnight
run may fix (no live mutation).

---

## 7. Commit

Two commits on `feat/v0.7-overnight` (this plan doc commits first, separately):
```
test(sso): pin Superset/Metabase BI SSO ceilings

- gate test_bi_sso_ceilings pins metabase=forward_auth BECAUSE the
  OSS image has no OIDC env (#28195) — blocks a silent native_oidc
  reclassify that would ship dead SSO
- pins superset=native_oidc with honest PARTIAL autologin
  (OAUTH_SKIP_PROVIDER_SELECTION never hides the local /login form;
  flag stays gated behind an else-branch False default)
- source-scan only; no live mutation, no new var
```
(Conventional Commits, subject ≤50 chars, surgeon-tone bullets ≤6, no
Co-Authored-By, no `--author`. Commit only — never push.)
