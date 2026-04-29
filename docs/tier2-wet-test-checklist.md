# Tier-2 wet-test checklist

> Operator runbook for verifying that a Tier-2 app deploys end-to-end:
> healthy container → routed by Traefik → guarded by Authentik → known
> to Wing /hub → GDPR row recorded → Bone event fired → Kuma probing
> → smoke catalog covering. Run this **after every blank** that touches
> a Tier-2 manifest. Re-runnable forever — copy-paste, no AI in the loop.

> **D8 mode (single pilot):** before running, demote the other Tier-2
> manifests so only one app deploys:
> ```bash
> cd /Users/pazny/projects/nOS
> mv apps/roundcube.yml apps/roundcube.yml.draft
> mv apps/documenso.yml apps/documenso.yml.draft
> ```
> Run the blank, walk this checklist for `twofauth`. When all rows are
> green, restore (`mv .draft .yml`) and run D9 (multi-pilot, same
> checklist for each).

---

## 0 · Pre-flight

```bash
cd /Users/pazny/projects/nOS

# Manifest parses
python3 -m module_utils.nos_app_parser apps/twofauth.yml
# → expect: "OK: twofauth"

# Tests still pass
python3 -m pytest tests/apps -q
# → expect: 72 passed (or more — additions only)

# Syntax check
ansible-playbook main.yml --syntax-check
# → expect: "playbook: main.yml" (no error lines)

# Image actually exists on the registry (catches typos before blank)
docker manifest inspect docker.io/2fauth/2fauth:6.1.3 >/dev/null && echo OK || echo FAIL
# → expect: OK
```

If any line fails, stop and fix BEFORE running the blank.

---

## 1 · Blank run

```bash
ansible-playbook main.yml -K -e blank=true
```

**Expected PLAY RECAP** (target row):
```
127.0.0.1 : ok=8XX changed=2XX unreachable=0 failed=0 skipped=3XX
```

If `failed > 0`, capture the fatal task name and last 30 log lines:
```bash
grep -B5 -A2 'fatal:' ~/.nos/ansible.log | tail -40
```

---

## 2 · Apps stack containers

```bash
docker compose -p apps ps --format 'table {{.Name}}\t{{.Status}}'
```

| Pilot | Expected containers (healthy) |
|---|---|
| twofauth (D8) | 1 row: `twofauth Up X seconds (healthy)` |
| + roundcube (D9) | + `roundcube Up X seconds (healthy)` |
| + documenso (D9) | + `documenso Up X seconds (healthy)` + `documenso-db Up X seconds (healthy)` |

If a row is missing or `restarting`:
```bash
docker compose -p apps logs --tail=80 <missing-name>
```

---

## 3 · Traefik route present

```bash
# Replace with each pilot's slug
SLUG=twofauth
curl -s http://127.0.0.1:8080/api/http/routers \
  | jq --arg slug "$SLUG" '.[] | select(.name | contains($slug))'
```

Expected fields:
- `rule`: contains `Host(\`twofauth.apps.dev.local\`)`
- `entryPoints`: includes `websecure`
- `tls`: present
- `middlewares`: includes `authentik@file`, `security-headers@file`, `compress@file`
- `status`: `enabled`

If empty:
- `docker logs infra-traefik-1 2>&1 | tail -30` — looking for `provider=docker` errors
- The container's compose labels (in `~/stacks/apps/overrides/auto.yml`)

---

## 4 · Authentik proxy provider + application

Open in a browser:
- `https://auth.dev.local/if/admin/#/core/providers` — search for `nos-app-twofauth` (a Proxy provider)
- `https://auth.dev.local/if/admin/#/core/applications` — search slug `twofauth`

Both must exist. The provider's "External Host" should be `https://twofauth.apps.dev.local`.

If missing:
- `grep "Reconverge Authentik blueprints" ~/.nos/ansible.log | tail -3` — check the task ran
- `docker compose -p infra exec authentik-server ak blueprints apply` — manual reconverge as last resort

---

## 5 · Wing /hub lists the app

Browser: `https://wing.dev.local/hub`. Search for `app_twofauth` row. Should show:
- `name`: 2FAuth
- `category`: security
- `tier`: 2
- `domain`: `twofauth.apps.dev.local`
- `enabled`: true

Or via SQLite:
```bash
sqlite3 ~/wing/wing.db "SELECT id, name, category, tier, domain FROM systems WHERE id LIKE 'app_%';"
```

If missing:
```bash
# Re-render service-registry.json with Tier-2 facts in scope
ls -la ~/projects/default/service-registry.json
grep '"name": "twofauth"' ~/projects/default/service-registry.json

# Then re-ingest into Wing
docker compose -p iiab -f ~/stacks/iiab/docker-compose.yml \
  -f ~/stacks/iiab/overrides/wing.yml \
  run --rm wing-cli php bin/ingest-registry.php
```

---

## 6 · GDPR Article 30 row recorded

```bash
sqlite3 ~/wing/wing.db \
  "SELECT id, name, legal_basis, retention_days, transfers_outside_eu FROM gdpr_processing WHERE id LIKE 'app_%';"
```

Expected:
- `app_twofauth | 2FAuth | legitimate_interests | -1 | 0`

Browser: `https://wing.dev.local/gdpr` — same row should be in the table.

If missing:
```bash
grep "Upsert GDPR" ~/.nos/ansible.log | tail -5
# Look for "OK upserted gdpr_processing.app_twofauth"
```

---

## 7 · Bone `app.deployed` event

```bash
tail -200 ~/.nos/events/playbook.jsonl | jq -c 'select(.type == "app.deployed")'
```

Expected one entry per onboarded app:
```json
{"ts":"...","run_id":"...","type":"app.deployed","source":"apps_runner","app_id":"twofauth","fqdn":"twofauth.apps.dev.local","category":"security","auth_mode":"proxy","version":"6.1.3","stack":"apps","tier":2}
```

If missing:
- `grep "Bone events delivery" ~/.nos/ansible.log | tail -5` — check signed vs unsigned path
- HTTP 401/403 unsigned path: `wing_events_hmac_secret` is empty — that's fine, expected

---

## 8 · Uptime Kuma monitor

Browser: `https://uptime.dev.local` (Kuma admin) → Monitors. Search for `App Twofauth`.

Should be:
- type: HTTP
- url: `https://twofauth.apps.dev.local`
- accepts: 200-299, 301, 302, 308, 401, 403
- tags: `apps`, `security`, `tier2`

If missing:
```bash
grep "Reconverge Uptime Kuma" ~/.nos/ansible.log | tail -3
# Should NOT show fatal — pre-existing first-bug fixed in dff52c1
```

---

## 9 · Smoke catalog runtime entry

```bash
ls -la /Users/pazny/projects/nOS/state/smoke-catalog.runtime.yml
cat /Users/pazny/projects/nOS/state/smoke-catalog.runtime.yml
```

Expected: file exists, contains `smoke_endpoints` list with one entry per pilot, each with:
```yaml
- id: app_twofauth
  url: "https://twofauth.apps.dev.local/"
  expect: [200, 301, 302, 308, 401, 502]
  tier: 2
  note: "Tier-2 app onboarded via apps_runner"
```

---

## 10 · Smoke probe passes

```bash
python3 tools/nos-smoke.py --tier 2
```

Expected: every Tier-2 row green (`ok: true`). Failures show as JSON lines with `ok: false` + a `status` code; common transient is `502` immediately after compose-up (Traefik upstream still starting), which the catalog already accepts.

---

## 11 · Browser flow — the human-eyeball test

1. Open `https://twofauth.apps.dev.local/` in a fresh private window.
2. Browser should redirect to `https://auth.dev.local/...` (Authentik login).
3. Log in with the operator credentials.
4. Browser redirects back to `https://twofauth.apps.dev.local/` — and the 2FAuth UI renders.
5. (Optional) Add a TOTP secret, log out, log back in via Authentik → secret survives.

If step 2 fails (no redirect to Authentik): proxy middleware not bound — re-check Authentik provider + outpost mapping.
If step 4 returns 502: container booted but Traefik hasn't seen healthcheck pass — wait 30s and retry.
If step 4 shows app's own login (not Authentik): proxy gate is OFF — `nginx.auth: proxy` not honoured (compare manifest).

---

## All 12 sections green = Track E sub-step DONE for this pilot.

Update [`docs/active-work.md`](active-work.md) with the result. If this was D8 (twofauth alone), restore Roundcube + Documenso and rerun this checklist for them — that's D9.

When all three pilots pass: track DONE; commit `feat(apps): tier-2 wet test verified — twofauth + roundcube + documenso live`.
