# v0.7 — Restart-handler command fix (then re-apply fail-loud)

> **Status:** plan. Supersedes the reverted `992dfab9` ("restart handlers must
> fail loud"). That commit removed `failed_when: false` from 49 docker-restart
> handlers — but every one of them runs a **broken command**, so fail-loud turned
> 49 silent no-ops into 49 guaranteed play-breaks. A blank tripped it at
> `infra-redis-1` and aborted before stack-up. Reverted in `c3c47337`.

## Problem / why

The role restart handlers all look like:

```yaml
- name: Restart <svc>
  ansible.builtin.shell: >
    {{ docker_bin }} compose -f "{{ stacks_dir }}/<stack>/docker-compose.yml" -p <stack>
    restart <svc>
```

The base `docker-compose.yml` declares only `services: {}` — the real service
definitions live in `overrides/<svc>.yml`, passed as extra `-f` flags **only by
the orchestrators** (`core-up.yml` / `stack-up.yml`). So `compose -f <base>
restart <svc>` operates on an empty project → **`no such service: <svc>`**.

This has been broken since the override pattern landed; `failed_when: false`
masked it (a **silent no-op** — the restart never actually happened). That mask
is itself the A17 Wing-502 bug class: config-on-disk changes, container keeps
running stale, playbook stays green. So the *intent* of `992dfab9` (fail loud)
is right — but you must **fix the command first**, or fail-loud just breaks the run.

## The handlers are NOT uniform — categorise before fixing

A mechanical `<stack>-<svc>-1` sweep is unsafe. Categories found (2026-06-14):

| Class | Examples | Shape | Fix |
|-------|----------|-------|-----|
| **A. base-only single-svc restart** | redis, grafana, gitea, nextcloud, … (~44) | `compose -f <base> -p <stack> restart <svc>` | address the running container directly |
| **B. multi-service restart** | erpnext | `restart erpnext-configurator erpnext-backend … (6 svcs)` | restart each container, or compose-with-overrides |
| **C. `up -d` not `restart`** | mailpit | `compose -p iiab up -d mailpit` (also base-only) | same fix, keep the recreate semantics if intended |
| **D. host command (not compose)** | acme → `brew services restart nginx` | host `brew services` | NOT base-only-broken — fail-loud is already correct here |
| **E. container_name + smart failed_when** | smtp_stalwart | sets `container_name:`, already has a guarded `failed_when:` | allowlisted — leave as-is |

`<stack>-<svc>-1` would be wrong for B (no `b2b-all-1`), C (verb), D (host), and
any service that sets `container_name:` (only stalwart today, excluded).

## Approach

For class **A** (the bulk), replace the broken compose call with a direct
container restart by the compose-default name `<stack>-<service>-1`
(nOS uses default compose naming everywhere except stalwart — verified: no
`container_name:` in any role compose template but stalwart):

```yaml
- name: Restart <svc>
  ansible.builtin.command: "{{ docker_bin }} restart <stack>-<svc>-1"
```

A more `container_name:`-robust variant (use if any future role sets it) —
address by compose labels so the name is irrelevant:

```yaml
ansible.builtin.shell: >
  {{ docker_bin }} restart
  "$({{ docker_bin }} ps -q
     -f label=com.docker.compose.project=<stack>
     -f label=com.docker.compose.service=<svc>)"
```

Per-class work:
- **B (erpnext):** restart all 6 containers (`b2b-erpnext-configurator-1`, `-backend-1`,
  `-frontend-1`, `-queue-short-1`, `-queue-long-1`, `-scheduler-1`) in one command,
  or run `compose` with the erpnext override `-f` so the service names resolve.
- **C (mailpit):** `docker restart iiab-mailpit-1` (decide: do we need `up -d`'s
  recreate-on-config-change, or is restart enough? the override re-render +
  next `stack-up` already recreates — restart is enough).
- **D (acme):** leave the host `brew services restart nginx`; re-apply fail-loud
  (drop `failed_when: false`) — it is a real host command that should surface.
- **E (stalwart):** no change.

Only **after** each command is verified to actually restart its container, drop
`failed_when: false` again (re-apply the `992dfab9` intent) — class by class.

## Gates it needs

Re-introduce `tests/anatomy/test_handler_restart_fails_loud.py`, but **strengthen**
it so the same trap can't recur:
1. No class-A/B/C handler may use `compose -f "<base>/docker-compose.yml" … restart`
   (the base-only pattern) — pin the corrected `docker restart <name>` form.
2. No class-A/B/C handler carries a blanket `failed_when: false` (the original
   doctrine), with the same documented allowlist for D-host / E-stalwart /
   launchctl best-effort handlers.
3. A handler whose service name contains a `-` must map to the right container
   segment (regression guard for the `calibre-web` → `iiab-calibre-web-1` shape).

## Verification recipe

1. `python3 -m pytest tests/anatomy/test_handler_restart_fails_loud.py -q`
2. `ansible-playbook main.yml --syntax-check`
3. **Wet-test on a blank** (every override renders fresh → every restart handler
   is notified → all flush): the run must reach `PLAY RECAP failed=0` with each
   restart handler `changed` (not failed). The previous blank proved the failure
   mode — this is the fix's acceptance test.
4. Targeted: after a no-op re-run, touch one override (bump a mem_limit), re-run
   `--tags <svc>`, confirm the handler restarts the real container (uptime resets)
   instead of erroring.

## Risk / what NOT to do

- Do **not** blanket-sed `<stack>-<svc>-1` — classes B/C/D/E break (see table).
- Do **not** re-drop `failed_when: false` before the command is verified working
  — that is exactly what `992dfab9` did and what this plan reverts.
- Keep class-D (acme host brew) and class-E (stalwart) out of the compose-fix.
