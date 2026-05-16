# nOS E2E SSO test suite — Playwright

Browser-based end-to-end tests for all nOS services with Authentik SSO login.
Covers **17 forward_auth services** (3 Tier-2 apps + 14 Tier-1) + health checks.

## One-time setup

```bash
cd tests/e2e
npm ci                          # installs Playwright + types
npx playwright install chromium # downloads the Chromium binary
```

## Running

The suite defaults to **ephemeral SSO identities** (A13.6 doctrine — see
[`docs/e2e-tester-identity.md`](../../docs/e2e-tester-identity.md)). A fresh
`nos-tester-e2e-<8hex>` user is provisioned in Authentik before the run and
revoked after.

```bash
# One-time after blank=true: fetch the nos-api token into ~/.nos/secrets.yml
python3 ../../tools/fetch-authentik-bootstrap-token.py

# Default: ephemeral tester in Tier-1 (provider) scope (reads token from secrets.yml)
NOS_HOST=dev.local npx playwright test

# Production
NOS_HOST=pazny.eu APPS_SUBDOMAIN=apps \
  AUTHENTIK_API_TOKEN=... \
  npx playwright test

# Single test (-g matches the title)
NOS_HOST=pazny.eu AUTHENTIK_API_TOKEN=... \
  npx playwright test -g "portainer"

# Different tier (provider | manager | user | guest)
NOS_TESTER_TIER=user AUTHENTIK_API_TOKEN=... npx playwright test
```

### Static-identity fallback (ad-hoc debugging)

If Authentik admin is unavailable, or you want a deterministic identity
for repeated manual runs:

```bash
NOS_SKIP_PROVISION=1 \
NOS_TESTER_USER=nos-tester \
NOS_TESTER_PASSWORD=<blueprint-password> \
npx playwright test
```

The blueprint user `nos-tester` is member of every RBAC tier so it can hit
any service, but using it bypasses the audit-trail isolation that ephemeral
identities provide. Don't use this in CI.

## What each test does

1. Navigate to service URL (e.g. `https://grafana.pazny.eu/`)
2. Traefik forward-auth middleware redirects to Authentik login
3. Fill ephemeral username → Next → fill random password → Submit
4. Redirect back to service → verify page renders with content

## Identity lifecycle

| Phase | What happens |
| --- | --- |
| globalSetup | `tools/e2e-auth-helper.py provision --tier <NOS_TESTER_TIER>` → writes `.playwright-out/tester.json` |
| Each test | reads `NOS_TESTER_JSON` env var → loads username + password |
| globalTeardown | `tools/e2e-auth-helper.py teardown --input .playwright-out/tester.json` → deletes Authentik user + revokes Wing token |

If the suite is killed (SIGKILL / Ctrl+C in a way that bypasses Node
shutdown handlers) the tester survives. Two recovery paths:

```bash
# Targeted: revoke the specific identity we know about
python3 tools/e2e-auth-helper.py teardown --input tests/e2e/.playwright-out/tester.json

# Belt-and-suspenders: delete every nos-tester-e2e-* older than 1h
python3 files/anatomy/scripts/sweep-orphan-testers.py
```

## Test structure

```
tests/e2e/
├── tier2-wet-test.spec.ts   # Tier-2 apps (3) + Tier-1 services (14) + health checks
├── global-setup.ts          # Provision ephemeral tester before the suite
├── global-teardown.ts       # Revoke tester after the suite (pass or fail)
├── journeys/                # Pytest-based journey tests (operator_login, rbac_admin, smoke...)
├── lib/                     # Python helpers (AuthentikAdmin, tester_identity, wing_token_admin)
├── playwright.config.ts     # Playwright config
└── README.md                # This file
```
