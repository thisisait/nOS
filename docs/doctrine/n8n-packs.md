# n8n packs — external pulls, one contract

> **Settled 2026-09-21.** Sibling of [`backoffice.md`](backoffice.md).
> The ČNB and ARES graphs are the first two instances; this file is the
> law so a third (VIES, ARES address, ČSSZ, …) does not grow a role,
> a Pulse plugin and a fire script.

## 1. What this is for

Public (or operator-gated) HTTP pulls into KEAP DataTables: ČNB FX,
ARES + nespolehlivý plátce, later the same shape. n8n is the **runner**
(nodes that already speak HTTP/SOAP). nOS is the **contract**: which
table, which egress, which GDPR row, whether the graph may run.

It is not: a new organ, a Dolibarr module, a Python hydrator per
register, or Pulse as a clock.

## 2. Three jobs, three owners (do not conflate)

| job | owner | not |
|---|---|---|
| **clock** | n8n `scheduleTrigger` in the graph | Pulse webhook, launchd |
| **hops** | n8n (HTTP Request / SOAP) | `tools/*-dtt.py` at runtime |
| **observe + inject** | playbook + Pulse **reader** | Pulse POSTing the webhook |

Pulse was asked for so a miss is a `pulse_runs` row with an exit code,
and so KEAP tokens do not live only inside n8n's sqlite. That is the
**observer / injector** job. Using Pulse as the clock duplicates cron
and still leaves the graph unimported.

`tools/*-dtt.py` stays the **oracle the gate scores** (ČNB already).
The live writer is n8n. Two implementations of the mapper are a cost;
the oracle is smaller than a second runner.

## 3. One pack = one YAML + one graph JSON

Do **not** add `ares-verify-base` / `n8n-fire.py` per pull. Do **not**
add a `pazny.*` role. A pack is:

```
files/anatomy/n8n/packs/<id>.yml      # contract (flag, table, cron, egress, gdpr)
files/anatomy/n8n/templates/<id>.json # graph (schedule + hops + upsert)
tools/<id>-dtt.py                     # optional oracle, only if the mapper can lie
```

Sketch of the YAML (names can move; the fields are the contract):

```yaml
id: ares-registry
table: party-registry-status
clock: n8n-schedule          # the only clock we will ship
cron: "10 5 * * *"           # must equal the schedule node in the JSON (gate)
workflow: ../templates/nos-pull-ares-registry.json
requires: [install_n8n, install_keap]
egress:
  - { host: ares.gov.cz, country: CZ }
  - { host: adisrws.mfcr.cz, country: CZ }
keap_write: true             # render public keap URL + SSRF allowlist + header cred
activate: operator           # playbook upserts inactive; UI Activate is the consent
gdpr: { ... }                # Art-30; processors = the named egress parties
```

Harvester: **n8n-base** (already the service plugin). `post.yml` logs
in once to mint `secret:n8n_api_key`, then uses the public API:

1. `POST/PUT /api/v1/workflows` keyed on `meta.nos.id` (idempotent).
2. Upsert one shared n8n credential `nos-keap-rw` from
   `keap_agent_token_rw` (secret stays in nOS derived secrets /
   Infisical, **injected** at converge — not pasted in the UI).
3. Render the KEAP base URL into the graph (or one instance variable)
   as `https://{{ keap_domain }}` — **not** loopback (container loopback
   is n8n itself, not the host). SSRF stays ON;
   `n8n_ssrf_allowed_hostnames` gains `keap_domain` when any pack
   sets `keap_write: true`. **The write goes to the agent API**
   (`/agent/v1`, bearer `keap_agent_token_rw`), the surface built for
   machine callers — never the `header_oidc` human route, which
   forward-auths and 302s a machine caller (the Woodpecker shape).
   Confirm once that the edge route passes bearer calls to `/agent/v1`
   through; if it does not, that is a Traefik route fix, not a reason
   to fall back to loopback.
4. Leave `active: false`. First-install consent is **Activate** in the
   UI. A later `n8n_auto_activate_packs: true` may exist; default off
   because these graphs call the Czech state. **Activation state is the
   operator's; graph CONTENT is git's** — the harvester overwrites the
   nodes of any workflow carrying `meta.nos.id` on every converge (it
   preserves only `active`). A UI edit to a pack graph is drift and
   will revert; an operator variant belongs in a copy without
   `meta.nos.id`. Say this in the graph's sticky note so the first UI
   tweak is not a surprise.

No human n8n API key. post.yml mints one into `~/.nos/secrets.yml`
(`secret:n8n_api_key`) and harvest + watch use that. Do not invent
`~/agents/tokens/n8n.token`.

REM-202 (`N8N_ENCRYPTION_KEY` unmanaged) is a **precondition** for
injected creds that survive a volume copy. Close it as part of this
pack, not as a drive-by.

## 4. Observability without Pulse-as-clock

One Pulse job on **n8n-base**, not per pack:

- `n8n-exec-watch` — `GET /api/v1/executions` (a minted API key written
  to `~/.nos/secrets.yml` as `secret:n8n_api_key`; the `/rest/*` cookie
  session is version-drifty internal API — mint the key once in
  post.yml and stop logging in).
- For each **active** pack id, two checks, both findings exit 1:
  a failed last execution, and **staleness** — last successful
  execution older than the pack's cron says it should be (next-fire
  computed from `cron` + one period of slack). "No executions" for an
  active pack is stale, not idle.
- **n8n unreachable = UNKNOWN (finding when any pack is active), never
  green.** A dead n8n fires no schedules and writes no failed
  executions — "no errors" from a stopped writer is the tailed-log
  trap, the exact shape the red-status doctrine exists for.
- Inactive packs / n8n not installed = idle 0.
- Optional: one imported n8n Error Trigger workflow that HMAC-POSTs
  Bone. That is also one graph, not N.

Face / Wing then see n8n pulls the way they see gitleaks: a Pulse row,
not a visit to the n8n exec list.

## 5. On-create (ARES) without a second clock

Daily schedule covers “all IČOs”. New thirdparty:

- **v1:** the daily run. Honest lag.
- **v2:** Dolibarr custom module POSTs n8n’s **webhook path on the same
  graph** (`scope=ico`). Still one graph, two triggers (schedule +
  webhook). Pulse does not fire it.

Do not add a 15-minute Pulse missing-scan.

## 6. Where the files live (submodule / extra repo)

| option | when |
|---|---|
| **In-tree `files/anatomy/n8n/`** | Default. A pack is a YAML+JSON, same weight as `apps/<name>.yml`. Praxis/consulting pulls belong here. |
| **Separate repo, harvested** | If a non-nOS author starts shipping pulls, or the pack count leaves the consulting-firm set. Shape = Coolify import: nOS keeps the harvester + GDPR/egress gate; the foreign repo keeps graphs. Pin a ref. |
| **Git submodule** | No. A submodule is a pin that CI and worktrees forget, for a problem harvest-from-URL already solves. KEAP is a clone-at-deploy, not a submodule, for the same reason. |

Growing nOS per use-case is **allowed in the pack directory**. It is
**refused** as a new plugin, a new Pulse fire script, a new Ansible
role, or a new organ.

## 7. What to delete / fold once this is built

- `ares-verify-base` Pulse fire + `tools/n8n-fire.py` (clock in the wrong organ).
- ČNB: keep the JSON; drop “import by hand”; same harvester; keep
  `tools/cnb-dtt.py` as oracle.
- ARES: same. `party-registry-status` table stays in nOS (the spine is
  nOS; the graph is a pack).

## 8. Gate (so a fourth pack cannot skip the contract)

- Every `packs/*.yml` has `id` == `meta.nos.id` in its JSON.
- `cron` in YAML equals the schedule node (string compare).
- JSON has no secrets, no RFC-1918 (existing ČNB gate).
- `keap_write: true` ⇒ template URLs contain `keap` host token or
  `{{ keap_domain }}` after render, never `127.0.0.1`.
- `egress[].host` appears in an HTTP node URL — and the converse:
  every non-KEAP host in any HTTP/SOAP node URL is declared in
  `egress`. One direction alone lets an undeclared hop ride along.
- `gdpr.processors` names every `egress` party (the Art-30 row and the
  egress list may not disagree).
- `keap_write: true` ⇒ the graph's KEAP node carries the injected
  credential reference (`nos-keap-rw`), not an inline header value.
- No pack ships `active: true` in git.
- `n8n-base` post.yml upserts every pack whose `requires` flags are on.

**Order of §7 (deletion) vs §4 (watch):** the watch job lands and is
seen reporting **before** `ares-verify-base` + `n8n-fire.py` are
deleted. Deleting the Pulse clock first leaves a window where a
missed pull is a row in nothing — the 2026-08-18 two-silent-nights
shape, rebuilt on purpose.

**REM-202 first:** `N8N_ENCRYPTION_KEY` becomes playbook-managed
before the harvester injects `nos-keap-rw`. An injected credential
under an unmanaged, volume-co-located key is a secret with a copy
problem (and GHSA-vrv8 already leaks decrypted creds into execution
data on the unpatched line).

Builder: implement §3 harvester on `pazny.n8n/tasks/post.yml` + pack
schema + fold ČNB and ARES onto it; then one Pulse watch job (§4).
Activate remains a click.
