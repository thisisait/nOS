# Post-run smoke testing — `tools/nos-smoke.py`

End-of-playbook check that every reachable service answers HTTP. Designed
to be:

- **Auto-extending** — every new manifest service with `domain_var` + an
  install flag enabled gets an automatic probe.
- **Operator-extensible** — drop entries into `state/smoke-catalog.yml`
  for custom paths, healthchecks, API endpoints, or Tier-2 apps.
- **Cross-tool** — JSONL output at `~/.nos/events/smoke.jsonl` (mirrors
  the `playbook.jsonl` lifecycle hook), parsed by Wing / Cursor / any
  shell consumer.
- **Fast** — parallel HEAD/GET probes via thread pool, full sweep ~1–7s.

## Quickstart

```bash
# Run the whole catalog (pretty table + summary)
python3 tools/nos-smoke.py

# Show only failures
python3 tools/nos-smoke.py --failed-only

# Filter by tier (1 = manifest-derived Tier-1, 2 = Tier-2 apps, 3 = framework)
python3 tools/nos-smoke.py --tier 1

# Filter by id substring
python3 tools/nos-smoke.py --include auth,wing,grafana

# Stream JSONL on stdout (for piping into jq / Wing ingest)
python3 tools/nos-smoke.py --json

# Disable JSONL persistence
python3 tools/nos-smoke.py --no-jsonl
```

Exit code = number of failed probes (capped at 127). `0` = clean.

The same script runs at the end of every `ansible-playbook main.yml` via
`tasks/post-smoke.yml`. The output appears as the second-to-last debug
block before the PLAY RECAP. To make smoke failures fail the playbook:

```bash
ansible-playbook main.yml -e nos_smoke_strict=true
```

## Adding a new endpoint

Edit `state/smoke-catalog.yml`. Schema:

```yaml
smoke_endpoints:
  - id: my-app                  # unique; matches manifest id to override its auto-probe
    url: "https://my-app.{{ instance_tld }}/health"
    expect: [200]               # int or list — accepted status codes
    when: "install_my_app | default(false)"   # Jinja-lite truthy expression
    timeout: 5                  # seconds (default 5)
    tier: 2                     # 1 manifest / 2 Tier-2 / 3 framework
    note: "Optional human description"
```

Default expect is `[200, 301, 302, 308]` — covers most HTTP front-door
status codes (login redirects, HTTPS forwarders, etc.).

Variables resolve from `default.config.yml` + `config.yml` (the same
files Ansible loads). The runner supports a Jinja-lite subset:

- `{{ var }}` — direct lookup
- `{{ var | default('fallback') }}` — fallback if undefined

Anything more complex (filters like `bool`, `length`, ternaries) is
intentionally not supported — keep catalog entries simple. If you need
heavier logic, push it into `default.config.yml` as a derived variable.

## Manifest auto-derivation

Every entry in `state/manifest.yml` with a `domain_var` and whose
`install_flag` resolves truthy gets a default probe of the form:

```
GET https://<domain_var value>/    # expect [200, 301, 302, 308]
```

Operator override: add an entry with the same `id` to
`state/smoke-catalog.yml` — the runner replaces the auto-derived probe
with the override.

## JSONL schema

Each probe writes one line to `~/.nos/events/smoke.jsonl`:

```json
{
  "ts": "2026-04-28T20:32:11Z",
  "run_id": "smoke_20260428T203211Z",
  "type": "smoke_result",
  "id": "authentik",
  "url": "https://auth.dev.local/",
  "expect": [200, 301, 302, 308],
  "status": 200,
  "duration_ms": 234,
  "ok": true,
  "error": null,
  "tier": 1
}
```

Consumer recipes:

```bash
# Last run summary
jq -r 'select(.type=="smoke_result") | "\(.ts)  \(.id)  \(.status)  \(.ok)"' \
   < ~/.nos/events/smoke.jsonl | tail -40

# Failed probes only, grouped by id
jq -r 'select(.type=="smoke_result" and .ok==false) | .id' \
   < ~/.nos/events/smoke.jsonl | sort | uniq -c | sort -rn
```

## Caveats

- The runner accepts mkcert dev certs (`insecure: true` default in
  `smoke_defaults`). For production smoke tests on a public TLD,
  override per-entry: `insecure: false`.
- HEAD requests are tried first; falls back to GET on 405 (HA's anti-CSRF
  rejects HEAD on `/`).
- Per-probe timeout default 5s — bump to 10–15s for slow-startup apps
  (Superset, Puter, Wing's first PHP page after a blank).
- Probes are parallel (default 20 workers). Lower with `--workers 4` on
  resource-constrained hosts.

## Tier-2 app integration (lands C2-C5)

When `pazny.apps_runner` (Tier-2 apps onboarder, in progress) renders a
new app, it appends a smoke entry to `state/smoke-catalog.yml`
automatically with:

- `id` = app slug
- `url` = `https://<slug>.apps.<tld>/`
- `expect` = `[200, 301, 302, 308, 401]` (401 covers auth-gated
  proxy_auth before login)
- `tier` = 2
- `when` = `"install_<slug> | default(false)"`

Operators don't normally edit those entries — they're regenerated each
run from `apps/<slug>.yml` manifest's `meta.ports[0]`.
