# v0.7 — Gitea Authentik OAuth source: CLI register + loud verify, pinned by a gate

**Status:** PLAN (review-ready, not implemented)
**Branch:** `feat/v0.7-overnight`
**Confirmed item:** SSO — Gitea Authentik OAuth source must register via the Gitea
CLI (`gitea admin auth add-oauth`), reconverge its secret, and **verify-loud**, with
the whole shape pinned by an anatomy gate so the 2026-06-13 "SSO lockout, oauth2
source row vanishes" saga cannot silently regress.

---

## 1. Problem / why

Gitea exposes **no REST endpoint for auth sources at any version**. The original
implementation POSTed to a non-existent `POST /api/v1/admin/identity-providers`,
which 404'd — and because that task ran `failed_when: false` + `no_log: true`, the
OAuth source **never registered** and the failure was invisible. With
`sso_autologin` hiding Gitea's local sign-in form, that means SSO-only login with
**no working "Sign in with Authentik" button = full operator lockout**. Root-caused
in the 2026-06-13 SSO audit (memory `local-first-git-topology`, `sso-mandatory-never-local-form`).

The fix is **already in the repo** and correct:

- `tasks/stacks/authentik_service_post.yml` (lines 18-136) — the live path:
  resolve-id → create-if-absent (`add-oauth`) → rotate-secret (`update-oauth --id`)
  → **loud verify** (`failed_when: "'authentik' not in stdout"`).
- `files/anatomy/plugins/gitea-base/hooks/post_compose.yml` — the transitional
  plugin-hook mirror (create-if-absent only; rotation owned by the role path).
- `roles/pazny.gitea/tasks/post.yml` (lines 95-133) — the SSO-mandatory guard that
  refuses a hidden form when the source is genuinely absent.

**The gap:** the CLI register / rotate / loud-verify shape in
`authentik_service_post.yml` has **no dedicated anatomy gate**. The only coverage is
`test_onboarding_signup_closed.py::test_gitea_external_only_registration`, which
asserts the **plugin hook** carries `add-oauth` + `--group-claim-name` and lacks the
`identity-providers` REST path — it does **not** cover the live
`authentik_service_post.yml` path, the secret-rotation leg, or the loud-verify
`failed_when`. So a regression that (a) reverts the live path to the REST endpoint,
(b) drops the `update-oauth` rotation, or (c) softens the verify to
`failed_when: false` would pass CI and re-introduce the silent lockout. Per the
non-negotiable rule "every code fix ships with a pytest anatomy gate," this item is a
**gate-the-existing-fix** task, not a behaviour change.

This mirrors the already-shipped loud-verify gates for the sibling services:
`test_portainer_sso_verify_loud.py` and the Nextcloud `user_oidc` verify — Gitea is
the one native-OIDC-via-CLI service whose verify is ungated.

---

## 2. Exact files to touch

### New (the deliverable)
- **`tests/anatomy/test_gitea_oauth_source_cli_register.py`** — the anatomy gate
  (mirrors `test_portainer_sso_verify_loud.py` in structure and tone).

### Possibly touched (only if the gate surfaces a real soft spot — see §3)
- `tasks/stacks/authentik_service_post.yml` — only if a `failed_when`/`no_log`
  asymmetry is found (e.g. the verify must stay loud; the create/rotate must stay
  `no_log`). Do **not** restructure working tasks just to satisfy the gate.
- `files/anatomy/plugins/gitea-base/hooks/post_compose.yml` — only if the gate
  chooses to also pin the plugin-hook mirror (recommended: assert parity, not
  rewrite).

### Read-only references (no edits)
- `roles/pazny.gitea/tasks/post.yml` — SSO-mandatory guard.
- `default.credentials.yml:303` — `authentik_oidc_gitea_client_secret`.
- `default.config.yml:422` — `sso_autologin_gitea` toggle.

---

## 3. Approach

A pure **offline static gate** (YAML/text assertions over the task files) — no live
system, no playbook run, fast, deterministic. Parse `authentik_service_post.yml` with
`yaml.safe_load_all`, locate the Gitea tasks by name prefix `[Authentik->Gitea]`, and
assert the shape. Concretely, the gate pins:

1. **CLI, not REST.** The Gitea create task uses `gitea admin auth add-oauth`
   (`argv` contains `add-oauth`); the file contains **no**
   `/api/v1/admin/identity-providers` path anywhere in the Gitea block. (Locks out
   the original 404 regression.)
2. **Create-if-absent + rotate split.** There is an `add-oauth` create task gated on
   an empty resolved source id (`(_gitea_ak_id.stdout ... | trim) == ''`) AND an
   `update-oauth --id` rotate task gated on a non-empty id. (Locks the idempotent
   two-leg shape — a single unconditional create would error on the second run.)
3. **Secret hygiene on the mutating legs.** Both create and rotate carry
   `no_log: true` (they pass `{{ global_password_prefix }}_pw_oidc_gitea`).
4. **Loud verify.** A verify task runs `gitea admin auth list` and fails loud:
   `failed_when` contains `'authentik' not in` and references
   `_gitea_oauth_verify.stdout`. It is **NOT** `failed_when: false`. (This is the
   single line that would have caught the original saga.)
5. **Group→admin mapping preserved.** The create argv carries `--group-claim-name`
   `groups` and `--admin-group` derived from
   `selectattr('tier', 'equalto', 1)` (tier-1 group set, rename-safe). (Stops a
   silent loss of admin auto-promotion.)
6. **`-u git` invariant.** Every Gitea CLI exec in the file passes `-u git` (the
   Gitea CLI refuses to run as root — same root cause as the admin-provisioning
   gate). Reuse the regex idea from `test_gitea_admin_provisioning.py`.
7. **(Optional) plugin-hook parity.** Assert `gitea-base/hooks/post_compose.yml`
   create step also uses `add-oauth` + `--group-claim-name` + tier-1 `--admin-group`
   and carries no `identity-providers` path — so the transitional mirror can't drift
   from the live path. (Light touch; `test_onboarding_signup_closed.py` already
   covers part of this — assert only the delta to avoid duplicate coverage.)

**Parsing note / robustness:** prefer structured parsing (`yaml.safe_load_all` →
filter docs whose `name` starts with `[Authentik->Gitea]`) over brittle full-file
substring greps, so a future reorder of unrelated tasks (Portainer/Nextcloud) doesn't
false-fail. Where a task uses `argv:` (the create/rotate), assert against the joined
argv list; where it uses a `>` folded `command:` (verify), assert against the string.
Keep each assertion message diagnostic (name the saga it guards), matching the
existing gates' tone.

**Why no behaviour change:** the live path already does all of (1)-(6) correctly. If
every assertion passes against the current tree on first write, the gate is doing its
only job — freezing the fix. If an assertion fails, that surfaces a real soft spot
(e.g. a missing `no_log`), which is then a one-line surgical edit to the task file
**plus** the gate — never a rewrite of working tasks.

---

## 4. Risks

- **Over-fitting the gate to incidental wording.** If the gate greps exact argv
  ordering or full task names, a benign refactor breaks it. *Mitigation:* assert on
  semantic tokens (`add-oauth`, `update-oauth`, `--group-claim-name`,
  `'authentik' not in`) and structured `name`-prefix filtering, not whole-line
  matches or positional argv indices.
- **Dual-path drift (role/plugin).** The plugin hook is a transitional mirror; if the
  gate pins it too rigidly it fights the eventual role-thinning cutover noted in the
  `authentik_service_post.yml` header. *Mitigation:* make the plugin-parity assertion
  (item 7) minimal and clearly labelled "transitional mirror — delete when the loader
  owns the tendon," so it's an obvious removal at cutover.
- **YAML-parse fragility.** `authentik_service_post.yml` mixes `argv` and folded
  scalars with Jinja braces; `yaml.safe_load_all` handles this fine (Jinja is opaque
  string content), but a `{{ '{{' }}` escape elsewhere in the file must not trip the
  loader. *Mitigation:* the Gitea block has no such escapes; load the whole file
  once, it already parses (the Nextcloud `'{{' '}}'` escapes are valid YAML strings).
- **False sense of completeness.** A static gate cannot prove the source actually
  registers on a live blank. *Mitigation:* state explicitly that runtime proof comes
  from the existing loud verify (`failed_when`) during a real run + the SSO-mandatory
  guard in `post.yml`; the gate's job is regression-locking the *shape*, and the
  verification recipe (§6) covers the dynamic check on the operator's next run.

---

## 5. Gates this needs

- **Primary deliverable:** `tests/anatomy/test_gitea_oauth_source_cli_register.py`
  (new), per §3. Must pass on the unmodified current tree.
- **Suite stays green:** `python3 -m pytest tests/anatomy/ -q` — no collateral
  failures, especially the adjacent `test_onboarding_signup_closed.py`,
  `test_gitea_admin_provisioning.py`, `test_portainer_sso_verify_loud.py`,
  `test_sso_doctrine.py`.
- **Syntax-check clean:** `ansible-playbook main.yml --syntax-check` (only relevant
  if a task file is touched; required regardless to honour the standing rule).
- **No new config vars** → the stock-Jinja gate (`test_config_stock_jinja_only.py`)
  is **not** triggered (this plan adds no `default.config.yml` /
  `default.credentials.yml` keys). If a future revision adds a var, it must carry a
  real default + stock filters.

---

## 6. Verification recipe

**Static (this is the gate — runs in CI + locally, no live system):**

```bash
# 1. New gate passes against the current (correct) tree
python3 -m pytest tests/anatomy/test_gitea_oauth_source_cli_register.py -q

# 2. Whole anatomy suite stays green
python3 -m pytest tests/anatomy/ -q

# 3. Playbook still parses (only if a task file was edited; safe to always run)
ansible-playbook main.yml --syntax-check
```

**Negative control (prove the gate actually bites — run locally, revert after):**

```bash
# Temporarily soften the loud verify and confirm the gate goes RED:
#   in tasks/stacks/authentik_service_post.yml, change the Verify task's
#   failed_when: "'authentik' not in (_gitea_oauth_verify.stdout | default(''))"
#   to   failed_when: false
python3 -m pytest tests/anatomy/test_gitea_oauth_source_cli_register.py -q   # MUST fail
git checkout -- tasks/stacks/authentik_service_post.yml                       # revert
```

**Dynamic (operator-run, READ-ONLY against the live system — NOT part of this PR):**

```bash
# Confirm the source is actually registered on the running Gitea (read-only):
docker compose -p devops exec -T -u git gitea gitea admin auth list   # expect a row named 'authentik'
# Confirm the button renders (read-only HTTP GET):
curl -sk https://git.<tld>/user/login | grep -i authentik             # expect the OAuth login link
```

The operator's next full run (`ansible-playbook main.yml --tags authentik,anatomy,gitea`
or a full converge) exercises the live register + loud verify; this PR ships only the
repo-side gate that pins the shape.

---

## 7. Out of scope / non-goals

- No change to the SSO doctrine, the `add-oauth` arguments, or the secret value.
- No live mutation, no blank, no service restart — repo edits only.
- No removal of the transitional `authentik_service_post.yml` include or the plugin
  hook — that role-thinning cutover is a separate, later item (tracked in the file
  header + memory `auto-wiring-epic-state`).
- No new feature toggle or credential.
