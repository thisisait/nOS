# Tier-2 wet-test checklist

> Operator runbook for verifying Tier-2 apps deploy end-to-end:
> healthy containers → routed by Traefik → guarded by Authentik →
> known to Wing /hub → GDPR rows recorded → Bone events fired →
> Kuma probing → smoke catalog covering. Run after every blank that
> touches a Tier-2 manifest. Re-runnable forever — copy-paste, no
> AI in the loop for routine verification.

> **Multi-pilot mode (default).** All three pilots
> (`twofauth`, `roundcube`, `documenso`) are deployed simultaneously.
> Plane (`apps/plane.yml.draft`) stays demoted — separate sprint when
> the three pilots are confirmed green. **Section 12** is the recovery
> protocol for the common case where 2 of 3 pilots are green and 1 is
> red (no full re-blank needed).

---

## 0 · Pre-flight

```bash
cd /Users/pazny/projects/nOS

# All three pilots parse cleanly
for APP in twofauth roundcube documenso; do
  python3 -m module_utils.nos_app_parser apps/$APP.yml \
    && echo "OK: $APP" || echo "FAIL: $APP"
done

# All apps tests still pass
python3 -m pytest tests/apps -q
# → expect: 85+ passed

# Syntax check
ansible-playbook main.yml --syntax-check
# → expect: "playbook: main.yml" (no error lines)

# All four pilot images actually exist on the registry (catches typos
# before blank). Skip if Docker not running yet.
for IMG in 2fauth/2fauth:6.1.3 \
           roundcube/roundcubemail:1.6.11-apache \
           documenso/documenso:v2.9.1 \
           postgres:15-alpine; do
  echo -n "$IMG → "
  docker manifest inspect docker.io/$IMG >/dev/null 2>&1 && echo OK || echo FAIL
done
```

If any line fails, stop and fix BEFORE running the blank.

---

## 1 · Blank run (operator-only)

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

**Bonus**: the last few lines of the recap should include
`[Apps] Inline smoke summary` showing Tier-2 probe results — added in
Phase 2 of this batch so failures surface immediately, not just at the
global post-smoke step.

---

## 2 · Apps stack containers — all four healthy

```bash
docker compose -p apps ps --format 'table {{.Name}}\t{{.Status}}'
```

**Expected:** four rows, all `Up X seconds (healthy)`:

| Container | Owning manifest |
|---|---|
| `twofauth` | `apps/twofauth.yml` |
| `roundcube` | `apps/roundcube.yml` |
| `documenso` | `apps/documenso.yml` |
| `documenso-db` | `apps/documenso.yml` |

If a row is missing or `restarting`, jump to **Section 12** for recovery
without a full re-blank.

```bash
# Diagnostic per-container (replace <name>)
docker compose -p apps logs --tail=80 <name>
```

---

## 3 · Traefik routes (per pilot)

```bash
for SLUG in twofauth roundcube documenso; do
  echo "── $SLUG ──"
  curl -s http://127.0.0.1:8080/api/http/routers \
    | jq --arg slug "$SLUG" '.[] | select(.name | contains($slug)) | {name, rule, status, middlewares}'
done
```

Expected per pilot:
- `rule`: contains `Host(\`<slug>.apps.dev.local\`)`
- `entryPoints`: includes `websecure`
- `tls`: present
- `middlewares`: includes `authentik@file`, `security-headers@file`, `compress@file`
- `status`: `enabled`

If empty:
- `docker logs infra-traefik-1 2>&1 | tail -30` — looking for `provider=docker` errors
- The container's compose labels (in `~/stacks/apps/overrides/auto.yml`)

---

## 4 · Authentik proxy providers + applications (per pilot)

Open in a browser:
- `https://auth.dev.local/if/admin/#/core/providers` — search for
  `nos-app-twofauth`, `nos-app-roundcube`, `nos-app-documenso` (Proxy
  providers)
- `https://auth.dev.local/if/admin/#/core/applications` — search slugs
  `twofauth`, `roundcube`, `documenso`

All three of each must exist. Each provider's "External Host" should be
`https://<slug>.apps.dev.local`.

If missing:
- `grep "Reconverge Authentik blueprints" ~/.nos/ansible.log | tail -3`
  — confirm the task ran
- `docker compose -p infra exec authentik-server ak blueprints apply`
  — manual reconverge as last resort

---

## 5 · Wing /hub lists all three apps

Browser: `https://wing.dev.local/hub`. Search for `app_twofauth`,
`app_roundcube`, `app_documenso`. Each should show:
- `tier`: 2
- `category`: matches manifest (security / mail / productivity)
- `domain`: `<slug>.apps.dev.local`
- `enabled`: true

Or via SQLite:
```bash
sqlite3 ~/wing/wing.db \
  "SELECT id, name, category, tier, domain FROM systems WHERE id LIKE 'app_%';"
```

If a row is missing:
```bash
# Re-render service-registry.json and re-ingest into Wing
ls -la ~/projects/default/service-registry.json
grep -c '"name": "twofauth"' ~/projects/default/service-registry.json
docker compose -p iiab -f ~/stacks/iiab/docker-compose.yml \
  -f ~/stacks/iiab/overrides/wing.yml \
  run --rm wing-cli php bin/ingest-registry.php
```

---

## 6 · GDPR Article 30 rows — three entries

```bash
sqlite3 ~/wing/wing.db \
  "SELECT id, name, legal_basis, retention_days, transfers_outside_eu \
   FROM gdpr_processing WHERE id LIKE 'app_%';"
```

Expected three rows:

| id | name | legal_basis | retention_days | transfers_outside_eu |
|---|---|---|---|---|
| app_twofauth | 2FAuth | legitimate_interests | -1 | 0 |
| app_roundcube | Roundcube | legitimate_interests | 365 | 0 |
| app_documenso | Documenso | contract | 365 | 0 |

Browser: `https://wing.dev.local/gdpr` — same three rows in the table.

If missing:
```bash
grep "OK upserted gdpr_processing" ~/.nos/ansible.log | tail -5
# Should see "OK upserted gdpr_processing.app_twofauth" etc.
```

---

## 7 · Bone `app.deployed` events — three entries

```bash
tail -300 ~/.nos/events/playbook.jsonl \
  | jq -c 'select(.type == "app.deployed")' \
  | tail -10
```

Expected one entry per onboarded app — for each pilot:
```json
{"ts":"...","run_id":"...","type":"app.deployed","source":"apps_runner","app_id":"<slug>","fqdn":"<slug>.apps.dev.local","category":"...","auth_mode":"proxy","version":"...","stack":"apps","tier":2}
```

If missing or short of three:
- `grep "Bone events delivery" ~/.nos/ansible.log | tail -5` — check
  signed vs unsigned path. HTTP 401/403 from unsigned path means
  `wing_events_hmac_secret` is not set; the unsigned fallback is
  expected and working as designed.

---

## 8 · Uptime Kuma monitors — three entries

Browser: `https://uptime.dev.local` (Kuma admin) → Monitors. Look for
`App Twofauth`, `App Roundcube`, `App Documenso`.

Each should be:
- type: HTTP
- url: `https://<slug>.apps.dev.local`
- accepts: 200-299, 301, 302, 308, 401, 403
- tags: `apps`, `<category>`, `tier2`

If missing:
```bash
grep "Reconverge Uptime Kuma" ~/.nos/ansible.log | tail -3
# Should NOT show fatal — pre-existing first-bug fixed in dff52c1
```

---

## 9 · Smoke catalog runtime — three entries

```bash
cat /Users/pazny/projects/nOS/state/smoke-catalog.runtime.yml
```

Expected: file exists, contains `smoke_endpoints` list with three
entries (`app_twofauth`, `app_roundcube`, `app_documenso`), each with:

```yaml
- id: app_<slug>
  url: "https://<slug>.apps.dev.local/"
  expect: [200, 301, 302, 308, 401, 502]
  tier: 2
  note: "Tier-2 app onboarded via apps_runner"
```

---

## 10 · Smoke probe — three Tier-2 rows green

```bash
python3 tools/nos-smoke.py --tier 2
```

Expected: all three Tier-2 rows green (`ok: true`). Common transient is
`502` immediately after compose-up (Traefik upstream still passing first
healthcheck) — already in the accepted-codes list, won't fail the row.

---

## 11 · Browser flow — the human-eyeball test (per pilot)

For each of `twofauth`, `roundcube`, `documenso`:

1. Open `https://<slug>.apps.dev.local/` in a fresh private window.
2. Browser should redirect to `https://auth.dev.local/...` (Authentik login).
3. Log in with the operator credentials.
4. Browser redirects back to `https://<slug>.apps.dev.local/` — and the
   app's UI renders.
5. (Optional) Pilot-specific sanity:
   - **twofauth**: add a TOTP secret, log out, log back in via
     Authentik → secret survives.
   - **roundcube**: the inbox UI loads (login attempts will fail until
     IMAP host is configured — that's expected for the pilot).
   - **documenso**: signup page renders; create a workspace; upload a
     PDF.

If step 2 fails (no redirect to Authentik): proxy middleware not bound
— re-check Authentik provider + outpost mapping (Section 4).
If step 4 returns 502: container booted but Traefik hasn't seen
healthcheck pass — wait 30s and retry (the `start_period: 60s` we added
in Phase 1 should cover this for fresh installs).
If step 4 shows the app's own login page (not Authentik): proxy gate is
OFF — `nginx.auth: proxy` not honoured (compare manifest).

---

## 12 · Recovery — one pilot red, others green

When sections 2-11 are mostly green for two pilots but red for one,
the fix-and-recover loop is much cheaper than a full re-blank.

1. Identify the failing pilot's container name (Section 2 output).
2. Inspect logs:
   ```bash
   docker compose -p apps logs --tail=100 <name>
   ```
3. Diagnose by failure pattern:

   | Symptom | Likely cause | Fix |
   |---|---|---|
   | Container restart-loops | Healthcheck fires before app is ready | Bump `start_period` to 90s or 120s in `apps/<slug>.yml` |
   | "Bind for 0.0.0.0:NN failed: address already in use" | Host port collision | Switch the manifest's `ports:` to `expose:` (Tier-2 doesn't need host bindings — Traefik routes via internal Docker network) |
   | "pull access denied" | Wrong image org / tag | Verify with `docker manifest inspect <image>`; check the slug-rename trap (Phase 3 W3.2) |
   | "FATAL: password authentication failed" | Postgres password drift across runs | Wipe the db volume: `docker compose -p apps down -v && rm -rf ~/stacks/apps/data/<slug>_db` (warning: data loss for this pilot only) |
   | App's own /login UI instead of Authentik redirect | Proxy middleware not bound | Re-check `nginx.auth: proxy` in manifest; re-run Authentik blueprint reconverge |

4. Fix the manifest at `apps/<slug>.yml`. Common manifest-level fixes:
   - Add or bump `start_period` in healthcheck
   - Replace `ports:` with `expose:` (let Traefik route)
   - Update image tag to a real one (verify with `docker manifest inspect`)

5. Re-run WITHOUT a blank (no full reset):
   ```bash
   ansible-playbook main.yml -K --tags apps,tier2,apps-runner
   ```
   The runner re-renders + `docker compose up apps --wait` brings the
   fixed container up without touching the healthy ones. Re-running
   --tags `apps` is safe — idempotent across the existing two pilots,
   only the broken one transitions state.

6. Re-run sections 3-11 for the recovered pilot only.

7. If the fix needed updates to a Tier-1 surface (e.g. Authentik blueprint
   change, Wing systems schema), re-run with broader tags:
   ```bash
   ansible-playbook main.yml -K --tags apps,authentik,wing,observability
   ```

---

## All 12 sections green for all three pilots = Track E DONE.

Commit: `feat(apps): tier-2 wet test verified — twofauth + roundcube + documenso live`
Update [`docs/active-work.md`](active-work.md) — flip pointer to Track F (D10).
Update [`.remember/remember.md`](../.remember/remember.md) — note Track E DONE,
next track F.

If a new pilot needs onboarding later (post-Track-F), use the Coolify
hybrid importer (`tools/import-coolify-template.py`) and walk this
checklist for the new addition only — Sections 2-11 are per-pilot,
Section 12 covers all common failure modes.
