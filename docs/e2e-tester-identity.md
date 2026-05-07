# E2E ephemeral SSO tester identity (Anatomy A13.6)

**TL;DR** — every Playwright/pytest journey gets its own freshly-minted, randomly-named, single-tier-membership Authentik user + Wing API token. The user is deleted and the token revoked when the test ends. Three lines of cleanup defense (per-test fixture teardown, atexit hook, manual sweep CLI) make leftover identities impossible in steady state.

---

## Why this exists

Vrstva A (commits `5d7b30b..70290de`, 2026-05-07) shipped four E2E journeys (`smoke`, `plugin_contract`, `halt_resume`, `approval_flow`) that emit `e2e_journey_*` events to Wing and surface in Grafana dashboard `40-e2e-journeys`. Two journeys were deferred:

* `operator_login` — needs an SSO-authenticated user
* `conductor_self_test` — needs the same plus Pulse trigger design

The static blueprint user `nos-tester` (in `roles/pazny.authentik/templates/blueprints/00-admin-groups.yaml.j2`) is member of **every** RBAC tier group, which makes it useless for asserting "tier-2 user gets 403 on /admin". Per-tier RBAC matrix testing requires per-tier identities — and once we accept that, ephemeral random per-test users are strictly safer:

* If a leak happens (CI logs, screenshot upload, stack-trace email), the blast radius is **one test**, not a long-lived shared credential.
* Random username `nos-tester-e2e-<8hex>` makes the audit trail trivially distinguishable from manual smoke probes (`actor_id LIKE 'nos-tester-e2e-%'`).
* No password rotation discipline needed — every identity is born with a new password and dies before the next one is born.

Operator mandate (verbatim, 2026-05-07):

> "kritické, aby playwright testing probíhal s SSO authorizovaným, auditovaným nos-tester userem, který musí vždy existovat (optimálně při každém běhu smazat a vygenerovat test user acc s náhodným heslem a novými tokeny, abychom zabránili leaku) se správnou RBAC rolí. Optimálně testing suite připravit dost abstraktně, aby šlo testovat i různé RBAC úrovně nad přibývajícími apps."

---

## Architecture

```
tests/e2e/
├── lib/                                     # the identity layer
│   ├── authentik_admin.py                  # AuthentikAdmin: user CRUD + group membership
│   ├── authentik_login.py                  # login_session: drives flow executor headlessly
│   ├── wing_token_admin.py                 # mint_token / revoke_token (subprocess provision-token.php)
│   └── tester_identity.py                  # provision_tester / teardown_tester / sweep_orphans
├── conftest.py                             # tester_identity fixture + atexit safety net
├── journeys/
│   ├── test_operator_login.py              # full SSO chain proof
│   └── test_rbac_admin.py                  # 4-tier RBAC matrix on /admin
└── ...

files/anatomy/scripts/
└── sweep-orphan-testers.py                 # standalone CLI for cron / Pulse / manual

tests/anatomy/
└── test_tester_identity_lib.py             # static contract gate (7 tests)
```

### Lifecycle

```
                       ┌───────────────────────────────────────────────┐
                       │ pytest collects test_admin_rbac[provider]     │
                       └─────────────────────┬─────────────────────────┘
                                             │
                                             ▼
        ┌────────────────────────────────────────────────────────────────┐
        │ tester_identity fixture (scope=function)                       │
        │   1. random username  nos-tester-e2e-a1b2c3d4                  │
        │   2. random password  secrets.token_urlsafe(32)                │
        │   3. POST   /core/users/                  → user_pk            │
        │   4. POST   /core/users/<pk>/set_password/                     │
        │   5. POST   /core/groups/<group_pk>/add_user/                  │
        │   6. subprocess  php provision-token.php  → wing_token         │
        │   7. yield TesterIdentity(...)                                 │
        └─────────────────────┬─────────────────────┬────────────────────┘
                              │                     │
                              ▼                     │
                    test runs (~1-3s)               │
                              │                     │
                              ▼                     │
                          test ends                 │
                              │                     │
        ┌─────────────────────▼─────────────────────▼────────────────────┐
        │ teardown                                                        │
        │   1. DELETE /core/users/<pk>/                                   │
        │   2. SQLite  DELETE FROM api_tokens WHERE name=tester:e2e:...   │
        └────────────────────────────────────────────────────────────────┘
```

### Three lines of cleanup defense

| # | Layer | Trigger | Catches |
|---|-------|---------|---------|
| 1 | Pytest fixture finalizer (`yield` → teardown) | normal test end + clean exception | 99% of cases |
| 2 | conftest atexit hook | pytest internal crash, fixture exception that swallowed cleanup | crashed teardowns |
| 3 | `sweep-orphan-testers.py` CLI | cron / manual / future Pulse job | OS-level kills, network partitions |

Each layer is independent: if (1) silently fails, (2) catches it; if (2) is bypassed by `os._exit`, (3) catches it on the next run.

---

## Test-author API

### Single-tier test

```python
import pytest

@pytest.mark.parametrize("tester_identity", ["provider"], indirect=True)
def test_admin_landing(journey, tester_identity):
    with journey("admin_landing") as j:
        with j.step("hit /admin") as s:
            r = requests.get(
                "http://127.0.0.1:9000/admin",
                headers={
                    "X-Authentik-Username": tester_identity.username,
                    "X-Authentik-Groups":   tester_identity.group_name,
                },
            )
            assert r.status_code == 200
```

### RBAC matrix test

```python
_MATRIX = [
    ("provider", "nos-providers", 200),
    ("manager",  "nos-managers",  403),
    ("user",     "nos-users",     403),
    ("guest",    "nos-guests",    403),
]

@pytest.mark.parametrize(
    "tester_identity,group_name,expected_status",
    _MATRIX,
    indirect=["tester_identity"],
    ids=[t[0] for t in _MATRIX],
)
def test_rbac(journey, tester_identity, group_name, expected_status):
    ...
```

This shape generalizes to **any** Wing presenter that calls `requireSuperAdmin()` or future `requireGroup(X)` guards. As more apps gain per-route RBAC the matrix lengthens; the harness doesn't change.

### Authentik full SSO chain

```python
from tests.e2e.lib.authentik_login import login_session

@pytest.mark.parametrize("tester_identity", ["provider"], indirect=True)
def test_real_sso(journey, tester_identity):
    with journey("real_sso") as j:
        with j.step("authentik_login") as s:
            sess = login_session(
                tester_identity.username,
                tester_identity.password,
            )
            # sess now carries authentik_session cookie — pass it through
            # Traefik to a forward-auth-protected service.
            r = sess.get("https://wing.dev.local/dashboard")
            assert r.status_code == 200
```

---

## Configuration

### Env vars

| Var | Default | Purpose |
|-----|---------|---------|
| `AUTHENTIK_API_TOKEN` | (none — falls through to secrets file) | bearer token for Authentik admin API |
| `AUTHENTIK_API_URL` | `http://127.0.0.1:9003/api/v3` | admin API base URL |
| `AUTHENTIK_API_TIMEOUT` | `60` | per-call timeout in seconds (bump if Authentik is slow on hammer-runs) |
| `AUTHENTIK_DOMAIN` | `auth.${NOS_HOST or TENANT_DOMAIN or dev.local}` | public Authentik host (cookies bind here) |
| `AUTHENTIK_FLOW_SLUG` | `default-authentication-flow` | flow executor slug |
| `WING_DATA_DIR` | `~/wing/data` | where `wing.db` lives (for token mint/revoke) |
| `WING_API_URL` | `http://127.0.0.1:9000` | Wing API base URL (used by journey HTTP calls) |
| `WING_EVENTS_HMAC_SECRET` | (none) | HMAC secret for journey telemetry events |

**Note on Authentik dev-instance flakiness.** During tight back-to-back full-suite runs against a single-replica local Authentik, response times can degrade non-linearly (we observed 7.9s for the first run and 234s for the fourth run, with the same code, same fixtures, same Authentik instance — by run #4 a single GET took 130s). The lib bumps default timeout to 60s and exposes the knob, but the right move when the suite gets sluggish is to give Authentik 60–90s of idle time to recover (its async worker queues drain), not chase the issue in our code. CI hitting a fresh container per run won't see this.

### Operator dev-bootstrap

The Authentik admin token is **not** auto-written to `~/.nos/secrets.yml` (the production playbook intentionally keeps stateless tokens out of the persistent secrets file). For local dev:

```bash
# 1. Login to https://auth.<tld>/ as akadmin (password from credentials.yml)
# 2. Directory → Tokens → find `nos-api` → click "Copy Key"
# 3. Append to your secrets file:
echo 'authentik_bootstrap_token: "<paste here>"' >> ~/.nos/secrets.yml

# 4. Run journeys
WING_EVENTS_HMAC_SECRET="$(grep bone_secret ~/.nos/secrets.yml | cut -d'"' -f2)" \
  python3 -m pytest tests/e2e/journeys/ -v
```

### Without Authentik creds → graceful skip

If no Authentik token is found, the `tester_identity` fixture calls `pytest.skip()`. Dependent journeys skip with a clean reason; the rest of the suite (`test_smoke`, `test_plugin_contract`, etc.) keeps running. **No journey test ever fails because of missing infra credentials** — that's a deliberate distinction: green = real success, skipped = environment limit, failed = real regression.

---

## Static contract gates

`tests/anatomy/test_tester_identity_lib.py` — 7 fast, no-network tests covering:

* lib imports cleanly
* `TIER_TO_GROUP` matches `default.config.yml::authentik_default_groups`
* `USERNAME_PREFIX = "nos-tester-e2e-"` (orphan-sweep contract)
* `WING_TOKEN_NAME_PREFIX = "tester:e2e:"` (audit-trail contract)
* conftest still registers the atexit hook
* the static blueprint user (`nos-tester`) doesn't collide with the ephemeral prefix

These run on every CI push (no Authentik / Wing required), so a refactor that breaks any of these contracts fails before it lands.

---

## Future work

* **Pulse cron `e2e-tester-orphan-sweep`** (24h) — scaffold a `e2e-harness-base` plugin manifest with the existing `sweep-orphan-testers.py` script. Belt #4. Tracked, not blocking.
* **Per-app RBAC matrix module** — add `tests/e2e/lib/rbac_matrix.py` declaring `expected[(app, route, tier)] = status` so RBAC journeys for new apps are one-line additions. Lands when a second RBAC-relevant app gets a presenter guard.
* **Token bootstrap from akadmin password** — replace the manual "copy token from UI" dev step with `authentik_login(akadmin) → POST /core/tokens/ → cache for session`. Lands if/when CI runs against a real Authentik (currently CI uses the static-contract gate path).
