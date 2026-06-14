# Plan — WordPress RBAC demotion edge case (last-admin floor + empty-claim safety)

Status: PLAN (not implemented)
Branch: `feat/v0.7-overnight`
Scope: repo-only code fix + new pytest anatomy gate. No live mutation.
Authoritative files: `roles/pazny.wordpress/files/rbac-role-sync.php`,
`tests/anatomy/test_wordpress_rbac_mirror.py`.

---

## 1. Problem / why

The WordPress RBAC mirror mu-plugin (`roles/pazny.wordpress/files/rbac-role-sync.php`)
mirrors Authentik group membership into the WordPress role on **every** OIDC login —
it hooks both `openid-connect-generic-user-create` and
`openid-connect-generic-update-user-using-current-claim`, so demotion is intended
behaviour (re-login with fewer groups → lower role). That part is correct and already
gated by `test_wordpress_rbac_mirror.py::test_mu_plugin_hooks_both_actions`.

The demotion path has **two unguarded edge cases** that can silently lock the operator
out of `/wp-admin`:

1. **Last-administrator demotion (lockout risk).** The map default
   (`default.config.yml:1147`) is
   `{"nos-providers":"administrator","nos-admins":"administrator", ...}`. If the operator's
   own OIDC identity is the *only* administrator and they are (even temporarily) removed
   from `nos-providers`/`nos-admins` in Authentik — or the `groups` claim arrives without
   those groups for any reason — `nos_rbac_sync_role()` computes `$winner = 'subscriber'`
   (the `NOS_RBAC_FALLBACK_ROLE`) and calls `$user->set_role('subscriber')`. WordPress
   happily demotes the last admin; the site now has **zero administrators reachable via
   SSO**. The documented break-glass (`wp-login.php` local `admin` account) still works,
   but the *OIDC operator* is locked out of admin with no warning and no floor. There is
   currently **no last-admin protection** (grep for `last_admin`/`floor`/`protect` in the
   role returns nothing).

2. **Empty/absent-groups conflated with "explicitly de-grouped".** When the `groups`
   claim key is *absent* (transient IdP hiccup, a scope/claim-mapping regression, or a
   provider that didn't emit `groups` on this particular token), `$user_claim['groups'] ?? []`
   yields `[]`. The loop finds no winner, `$winner` stays at the `subscriber` fallback, and
   the user is demoted — even though the login carried **no role information at all**.
   "I got no group info this login" is not the same event as "I was explicitly removed from
   every group", but the current code treats them identically. A missing-claim transient
   should **leave the existing role untouched**, not demote.

Both bugs are demotion-direction-only — promotion and steady-state are fine — so they
hide until a group is removed or a claim regresses, exactly the kind of latent failure
that bites unsupervised. This is a `v0.7` hardening item: make demotion *safe* without
removing the (correct) demotion-on-regroup behaviour.

> Doctrine anchors: SSO-mandatory / break-glass (`onboarding-pure-sso-doctrine`,
> `mfa-posture-and-lockout` — passkey-only lockout + static break-glass is the standing
> pattern); destructive-op safety (operator wants the *least surprising*, reversible
> behaviour by default). A silent last-admin demotion is the WordPress analogue of the
> Authentik passkey lockout the operator already guards against elsewhere.

---

## 2. Exact files / roles to touch

| File | Change |
|------|--------|
| `roles/pazny.wordpress/files/rbac-role-sync.php` | Add (a) **empty-claim guard** — if `groups` key is absent OR no mapped role matched, **do not demote**; (b) **last-administrator floor** — never strip `administrator` from a user via this hook if they would be the last remaining admin; refactor the decision into a **pure function** `nos_rbac_decide_role($groups, $map, $current_roles)` returning the target role (or `null` = leave untouched) so it is unit-testable without a live WP. |
| `tests/anatomy/test_wordpress_rbac_mirror.py` | Add the new edge-case gate cases (extend the existing file — it already owns this contract). |
| `roles/pazny.wordpress/README.md` | One short subsection documenting the demotion semantics + last-admin floor (doc-vs-code honesty: the file's header comment currently promises "demoted to the fallback role" with no caveat — update it to match the new guarded behaviour). |

**Not touched:** `default.config.yml` (the JSON map literal is unchanged — no new var, so
the stock-Jinja trap does not apply), the compose extension render, `tasks/post.yml`,
`tasks/main.yml`. The mu-plugin is mounted read-only via the existing single mu-plugins
**directory** mount (`/wp-content/mu-plugins:ro`) — no mount change.

---

## 3. Approach

### 3a. Refactor to a pure decision function (testability + correctness)

Extract the winner computation into a side-effect-free function that the hook calls:

```php
/**
 * Decide the target WP role for an OIDC login.
 * @param array      $groups        groups claim (already normalised to a list)
 * @param array      $map           group => role
 * @param string[]   $current_roles $user->roles
 * @param bool       $groups_present whether the 'groups' key existed in the claim
 * @return string|null  target role, or null = LEAVE ROLE UNTOUCHED
 */
function nos_rbac_decide_role(array $groups, array $map, array $current_roles, bool $groups_present)
```

Decision table (the structural fix):

| Condition | Result |
|-----------|--------|
| `groups` claim **key absent** (`$groups_present === false`) | `null` → leave untouched (transient/claim-less login never demotes) |
| at least one group maps to a valid role | highest-privilege mapped role (existing behaviour, unchanged) |
| `groups` present + non-empty, but **none map** to a valid role | demote to `NOS_RBAC_FALLBACK_ROLE` (explicit de-mapping → fallback is correct) |
| `groups` present but **empty list** (`[]`) | demote to fallback (explicitly in zero groups) |
| computed target would **remove `administrator`** from a user who is the **last admin** | clamp to keep `administrator` (last-admin floor) |

The role-existence check (`get_role($role)`) stays in the *hook* wrapper (it needs live
WP), but the pure function takes the already-validated map so the floor/empty logic is
unit-testable. The last-admin count uses a WP-side count callback injected by the wrapper:

```php
function nos_rbac_sync_role($user, $user_claim) {
    // ... env + json_decode + groups normalisation + groups_present detection ...
    $target = nos_rbac_decide_role($groups, $valid_map, (array) $user->roles, $groups_present);
    if ($target === null) { return; }                       // leave untouched
    $would_demote_admin = in_array('administrator', (array) $user->roles, true)
                          && $target !== 'administrator';
    if ($would_demote_admin && nos_rbac_admin_count() <= 1) {
        return; // last-admin floor — refuse to strip the only administrator
    }
    if (!in_array($target, (array) $user->roles, true)) {
        $user->set_role($target);
    }
}
```

`nos_rbac_admin_count()` wraps `count(get_users(['role' => 'administrator', 'fields' => 'ID']))`
(guarded `function_exists('get_users')`). It counts **all** admins including the local
break-glass `admin` — that is the intended floor: as long as one administrator exists,
the floor allows demotion; only the literal last one is protected.

### 3b. Documentation honesty

Update the mu-plugin header block and `README.md` so "demoted to the fallback role" reads
"demoted to the fallback role **unless** (a) the claim carried no `groups` key — then the
role is left untouched, or (b) the user is the last remaining administrator — then the
admin role is preserved." Keep it ≤ a short paragraph.

---

## 4. Risks

- **R1 — Over-broad floor disables legitimate demotion.** Mitigation: floor is scoped to
  *the last admin only* (`count <= 1`) and *only* blocks the admin→lower transition; with
  ≥2 admins, demotion proceeds normally. Gated explicitly (see §5, case "two admins → demote
  proceeds").
- **R2 — Empty-list vs absent-key detection is subtle.** `array_key_exists('groups', $claim)`
  is the discriminator; `$user_claim['groups'] ?? []` collapses both to `[]` so the wrapper
  must capture `$groups_present = array_key_exists('groups', $user_claim)` *before*
  normalisation. Gated by a case that passes `[]` (present → demote) vs omits the key
  (absent → untouched).
- **R3 — `get_users()` cost on every login.** A single indexed role query per OIDC login is
  cheap and only runs on the demote-admin branch (short-circuited by the
  `in_array('administrator', ...)` pre-check). No hot-path regression.
- **R4 — Behaviour change could surprise an operator who *wanted* the demotion.** This is a
  net-safer default and reversible: removing a *second* admin makes the floor a no-op. Risk
  accepted; documented in README.
- **R5 — PHP not present in some CI lanes.** The dynamic-eval gate self-skips when `php` is
  absent (mirrors `test_lockfile_sync.py`); the pytest job provisions PHP 8.3
  (`.github/workflows/ci.yml`), so it runs there. Static-source assertions need no PHP and
  always run.

---

## 5. Gates it needs (`tests/anatomy/test_wordpress_rbac_mirror.py`)

Extend the existing file (it owns this contract). New cases:

**Static-source (no PHP — always run):**
- `test_mu_plugin_has_last_admin_floor` — source contains `nos_rbac_admin_count`, the
  `<= 1` (or `< 2`) comparison, and an early `return` on the demote-admin branch.
- `test_mu_plugin_leaves_role_untouched_on_absent_groups` — source uses
  `array_key_exists('groups'` (the present-vs-absent discriminator) and the decide function
  can return `null`.
- `test_decide_role_is_pure_function` — `function nos_rbac_decide_role` exists and the hook
  calls it (regression pin against re-inlining the logic).

**Dynamic behaviour (PHP-eval; `pytest.importorskip`-style self-skip when `shutil.which("php")`
is None):** load the file with WP symbols **stubbed** (define `ABSPATH`, no-op `add_action`,
a fake `get_role` returning truthy for known roles, an injectable admin-count) and assert
`nos_rbac_decide_role(...)` returns:

| Input (groups, map, current_roles, groups_present) | Expected |
|----|----|
| `['nos-admins']`, default map, `['subscriber']`, present | `administrator` (promote, unchanged) |
| `['nos-managers','nos-users']`, map, `['subscriber']`, present | `editor` (highest-priv wins, unchanged) |
| `[]`, map, `['administrator']`, **absent** | `null` (leave untouched — transient claim) |
| `[]`, map, `['administrator']`, **present** | `subscriber` (explicitly de-grouped → demote) |
| `['unmapped-group']`, map, `['editor']`, present | `subscriber` (present, none map → fallback) |

Plus a **wrapper-level** floor assertion via the same stub harness: with `admin_count = 1`,
a present-but-empty claim on the last admin → `set_role` is **NOT** called; with
`admin_count = 2`, the same input **does** call `set_role('subscriber')`. (Capture
`set_role` invocation in a stub `WP_User`.)

**Suite-green requirement:** all five existing cases in the file must still pass; the new
cases are additive. Run:

```bash
python3 -m pytest tests/anatomy/test_wordpress_rbac_mirror.py -q   # extended gate
python3 -m pytest tests/anatomy -q                                 # full anatomy suite green
php -l roles/pazny.wordpress/files/rbac-role-sync.php              # mu-plugin lints clean
ansible-playbook main.yml --syntax-check                           # playbook still parses
```

---

## 6. Verification recipe (repo-only, no live mutation)

1. **Baseline (pre-change):**
   `python3 -m pytest tests/anatomy/test_wordpress_rbac_mirror.py -q` → 5 passed;
   `php -l roles/pazny.wordpress/files/rbac-role-sync.php` → no syntax errors.
2. **After the mu-plugin edit:** `php -l ...` clean; the new pure function evaluates the
   §5 decision table correctly under the PHP stub harness.
3. **After the gate edit:** `python3 -m pytest tests/anatomy/test_wordpress_rbac_mirror.py -q`
   → all cases green (old + new); confirm the dynamic cases actually executed (not skipped)
   on a host with `php` in PATH, and self-skip cleanly when PHP is removed from PATH
   (`PATH=/usr/bin python3 -m pytest ...` simulating no-php — static cases still run).
4. **Regression sweep:** `python3 -m pytest tests/anatomy -q` → full suite green.
5. **Syntax:** `ansible-playbook main.yml --syntax-check` → clean.
6. **Read-only live sanity (optional, no writes):** on the running stack, confirm the
   demotion regression is real by inspecting current admin count without changing anything —
   `docker compose -p iiab exec -T wordpress wp user list --role=administrator --field=ID --allow-root`
   (READ-only `wp user list`; never `wp user update`/`set-role`). Documents the floor's
   premise; not required for the gate.

---

## 7. Commit (branch-only, never push)

```
fix(wordpress): floor last-admin + safe empty-claim RBAC

- rbac-role-sync demoted the last OIDC admin to subscriber silently
- absent groups claim conflated with explicit de-grouping → wrong demote
- extract nos_rbac_decide_role pure fn; null = leave role untouched
- last-admin floor: never strip the only administrator via OIDC hook
- gate: test_wordpress_rbac_mirror covers floor + absent/empty claim
```

Conventional Commit, subject ≤50 chars, surgeon-tone bullets ≤6, no Co-Authored-By, no
`--author`. Lands on `feat/v0.7-overnight` only.
