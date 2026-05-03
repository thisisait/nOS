# Post-blank verification — operator entry point

> **TL;DR** — when `ansible-playbook main.yml -K -e blank=true` finishes:
> ```bash
> bash tools/post-blank.sh
> ```
> If it prints **GREEN**, you're done. If **RED**, follow the
> "Failure triage" section below.

This is the **single canonical sequence** to run after every blank.
Replaces the ad-hoc "ok now what" mental checklist that used to live
across `docs/tier2-wet-test-checklist.md`, `tools/nos-smoke.py`,
`tools/wing-telemetry-smoke.py`, and tribal memory.

---

## What `tools/post-blank.sh` actually runs

```
[1/3] NOS_WET=1 pytest tests/wet -v
        ↳ 14 tests covering wet-test checklist sections 6/7/9:
          • SQLite GDPR rows in ~/wing/wing.db
          • Bone `app.deployed` events in ~/.nos/events/playbook.jsonl
          • smoke-catalog.runtime.yml has 3 Tier-2 entries
        ↳ NOS_WET=1 → missing artefacts FAIL (vs. SKIP in casual runs)

[2/3] python3 tools/nos-smoke.py
        ↳ HTTP probes every service in state/manifest.yml + every
          Tier-2 entry from state/smoke-catalog.runtime.yml
        ↳ Status code expectations come from the catalog (e.g. 401 is
          OK for Authentik-protected pages — that's the redirect)

[3/3] Wing UI deep-links printed to stdout
        ↳ /timeline, /hub, /gdpr, /migrations, /upgrades, /coexistence
        ↳ Set POST_BLANK_OPEN=1 to auto-`open` /timeline on macOS
```

The script keeps going on failure (no `set -e` on the steps) so even
when step 1 reds, you still see the smoke output and the UI URLs.
Final exit code: `0` only if **both** wet tests and smoke pass.

---

## Env knobs (rare)

| Var | Default | Purpose |
|---|---|---|
| `NOS_HOST` | `dev.local` | tenant domain — flip to `pazny.eu` for the LE-prod box |
| `NOS_WET_STRICT` | `1` | set to `0` to make missing artefacts SKIP not FAIL (pre-blank dev) |
| `NOS_TIER` | `all` | `1` = manifest-derived only, `2` = Tier-2 apps only |
| `POST_BLANK_OPEN` | `0` | `1` = auto-`open https://wing.${NOS_HOST}/timeline` |

---

## Wing UI walk-through (the human-eyeball pass)

After `tools/post-blank.sh` prints GREEN, open these in order:

1. **`/timeline`** — flat list of every callback plugin event from the
   blank. Look for: no red rows, ~30-50 events per run, `app.deployed ×3`
   near the bottom.
2. **`/hub`** — systems registry. Filter `tier=2` → 3 rows
   (`app_twofauth`, `app_roundcube`, `app_documenso`).
3. **`/gdpr`** — Article 30 records. Same 3 `app_*` rows; legal_basis
   per `apps/<slug>.yml`'s `gdpr.legal_basis` field.
4. **`/migrations`** — should show the post-2026-05-03 migrations only;
   `_archived-2026-05-01-bone-wing-to-container.yml` must NOT appear.
5. **`/upgrades`** — empty by default (upgrades are explicit,
   `--tags upgrade -e upgrade_service=<svc>`).
6. **`/coexistence`** — empty unless an active dual-version provision.

---

## Failure triage (RED verdict)

`tools/post-blank.sh` exits `1` on any wet or smoke red. Diagnostic
recipes are organized by failure shape:

### A. wet test fails

The test name encodes the wet-test checklist Section ID. Cross-reference:

| Test class | Checklist section | First diagnostic |
|---|---|---|
| `TestSection6_GdprRows` | §6 GDPR rows | `grep "OK upserted gdpr_processing" ~/.nos/ansible.log \| tail -5` |
| `TestSection7_BoneEvents` | §7 Bone events | `grep "Bone events delivery" ~/.nos/ansible.log \| tail -5` |
| `TestSection9_SmokeCatalog` | §9 smoke catalog | `grep "Extend smoke catalog" ~/.nos/ansible.log \| tail -5` |

Recovery for sections 6 & 9 is usually `--tags apps`-only re-run (no
need for full blank). Section 7 (Bone events) needs the bone container
healthy first — check `docker compose -p infra ps bone`.

### B. smoke probe fails (1-2 services)

```bash
python3 tools/nos-smoke.py --failed-only       # narrow to red rows
python3 tools/nos-smoke.py --failed-only --json  # machine-readable
```

For each red row check:
- `docker compose -p <stack> ps <svc>` — is it healthy?
- `docker compose -p <stack> logs --tail=50 <svc>` — startup error?
- Traefik's view: `curl -s http://127.0.0.1:8080/api/http/routers \
  | jq '.[] | select(.name | startswith("<slug>"))'` — is the router up?
- Authentik provider for the service exists and is assigned to outpost?

### C. smoke probe fails wholesale (most/all services)

Almost always a Traefik / DNS / cert problem, not per-service. Check:
- Traefik container is running and binding 443
  (`docker compose -p infra ps traefik`)
- `dnsmasq` is forwarding `*.${NOS_HOST}` to 127.0.0.1
  (`scutil --dns | grep -A3 dev.local`)
- mkcert root CA is in System keychain
  (`security find-certificate -a -p /Library/Keychains/System.keychain | grep -c "mkcert"`)

### D. Wing UI returns 502 / 500

Either Wing or `wing-nginx` is sick. Until A3.5 (FrankenPHP host-revert)
both run as containers in `iiab` stack:
```bash
docker compose -p iiab ps wing wing-nginx
docker compose -p iiab logs --tail=100 wing
```

If Wing's PHP-FPM is up but the UI is empty, the SQLite migration didn't
run or didn't ingest. Force re-ingest:
```bash
docker compose -p iiab exec wing-cli php bin/ingest-registry.php
docker compose -p iiab exec wing-cli php bin/migrate.php --apply
```

---

## Cowork autonomy

Once a Cowork session has shell pass + browser, it runs
`tools/post-blank.sh`, parses the exit code + stderr, and either:

- **Green** → confirms in chat, files no commit, idle until next blank.
- **Red, small fix** → opens the failing manifest, applies a known
  recipe (`start_period` bump, image tag bump, env var fill-in), commits
  as `fix(...): ...`, re-runs `--tags apps` only.
- **Red, judgment-required** → files a question to the operator's queue
  with the failure context and proposed direction; does NOT commit.

The Cowork dispatch prompt lives at
[`docs/cowork-wet-test-prompt.md`](cowork-wet-test-prompt.md).

---

## Related docs

- [`tier2-wet-test-checklist.md`](tier2-wet-test-checklist.md) — the
  human-readable canonical checklist (12 sections). `post-blank.sh`
  automates sections 6/7/9 (Python) and parts of 2/3/5/8 via smoke
  probes; sections 4/11 (Authentik admin UI, browser flow) stay manual
  until Track P proper lands real Playwright bodies.
- [`wet-test-automation.md`](wet-test-automation.md) — Track P
  architecture (Playwright + Cowork loop). `post-blank.sh` is the
  shell-level primitive Cowork drives.
- [`active-work.md`](active-work.md) — current sprint state.
