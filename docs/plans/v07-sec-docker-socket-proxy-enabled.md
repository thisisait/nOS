# v0.7 SEC — Docker socket-proxy enabled (eliminate / justify every raw `docker.sock` mount)

Status: PLAN (do not implement from this doc without operator review)
Branch: `feat/v0.7-overnight`
Related: REM-001 (resolved), REM-002 (pending), C1 image-pin sweep, 2026-06-10 serial security review.

---

## 1. Problem / why

`/var/run/docker.sock` is **root on the host**: any container that bind-mounts it can
`docker run -v /:/host --privileged ...` and own the machine. nOS already shipped the
mitigation for the highest-value target — Portainer + Traefik talk to
`tecnativa/docker-socket-proxy` (`tcp://docker-socket-proxy:2375`) instead of the raw
socket (REM-001 resolved). But a repo-wide audit shows the socket-proxy doctrine is
**not yet a complete, enforced invariant**: three roles still bind the raw socket, and
nothing in `tests/anatomy/` stops a fourth from appearing.

Current direct `/var/run/docker.sock` consumers (live, verified by grep over `roles/` +
`templates/stacks/`):

| # | Mount site | Mode | Why it mounts the socket | Proxy-eligible today? |
|---|------------|------|--------------------------|-----------------------|
| 1 | `roles/pazny.woodpecker/templates/compose.yml.j2:78` (woodpecker-agent) | **rw** | Spawns CI pipeline step containers via the docker backend | **No** — needs `POST` + container create/attach/exec; lives on `devops_net`, can't reach `infra_net`; proxy guards but doesn't shrink the blast radius for a backend that *must* create arbitrary containers |
| 2 | `roles/pazny.watchtower/templates/compose.yml.j2:14` (watchtower) | **rw** | Pulls new image tags + recreates containers | **Partial** — needs `POST`/`IMAGES`/`CONTAINERS` write verbs; lives on `iiab_net` |
| 3 | `roles/pazny.grafana/templates/compose.yml.j2:200` (cadvisor) | **ro** | Container resource metrics | **Read-only already**; proxy could front it but cAdvisor also needs `/sys`, `/var/lib/docker`, `privileged: true`, so proxying the socket alone is cosmetic |
| 4 | `templates/stacks/infra/docker-compose.yml.j2:33` (docker-socket-proxy itself) | **ro** | This *is* the proxy — the single sanctioned raw mount | N/A (the sanctioned mount) |

Note: `roles/pazny.portainer/tasks/post.yml:323` `URL: "unix:///var/run/docker.sock"`
is **NOT a socket mount** — it is the `EndpointCreationType=1` Portainer-API form field
value, overridden at runtime by Portainer's `--host tcp://docker-socket-proxy:2375`
command flag (`roles/pazny.portainer/templates/compose.yml.j2:21`). Leave it alone; it
is cosmetic API-payload text, not a bind.

**The honest scope of this item is therefore NOT "remove all four mounts."** Woodpecker's
docker backend and Watchtower's recreate loop legitimately need write access to the Docker
API, and the proxy is a *narrowing* tool, not a magic isolator. The deliverable is:

1. **Make the socket-proxy doctrine an enforced invariant** — a gate that inventories every
   raw `docker.sock` mount in the repo and fails on any new one not in a reviewed allowlist
   (each allowlist entry carries a one-line justification, exactly like
   `test_image_pin_hygiene.EXCEPTIONS`).
2. **Front the proxy-eligible consumers** where it genuinely shrinks the surface:
   - **Watchtower** → route through a dedicated **write-scoped** socket-proxy on its own
     network, dropping the raw rw mount.
   - **cAdvisor** → leave as-is (`:ro` + `privileged` + host paths make socket-proxying
     cosmetic) but record it in the allowlist with that reason.
   - **Woodpecker-agent** → leave raw (backend requires it) but record it in the allowlist
     and cross-reference REM-002's "rootless backend" long-term track.
3. **Pin the proxy env-surface invariant** so a future edit can't silently widen the API
   verbs (e.g. flip `EXEC: 1` unconditionally) without a gate flagging it.

This converts an implicit, partially-applied mitigation into an explicit, test-pinned one
— matching the C1 image-pin pattern (`test_image_pin_hygiene.py`) that already guards the
proxy *image*.

---

## 2. Exact files / roles to touch

### New gate (mandatory — this is the load-bearing deliverable)
- `tests/anatomy/test_docker_socket_proxy.py` — NEW. Three assertions (see §4).

### Watchtower → dedicated write-scoped proxy (the one real wiring change)
- `templates/stacks/iiab/docker-compose.yml.j2` — add a second, **write-scoped**
  `docker-socket-proxy-rw` service (own name, own network alias) gated behind
  `install_watchtower | default(false)`. Env grants only `CONTAINERS:1 IMAGES:1 POST:1`
  (+ the minimum verbs watchtower needs to pull+recreate; verify against watchtower's
  required-API doc during implementation — it needs container list/inspect, image
  pull/inspect, container stop/start/create/remove). NO `EXEC`, NO `BUILD`, NO `INFO`.
- `roles/pazny.watchtower/templates/compose.yml.j2` — replace the
  `- /var/run/docker.sock:/var/run/docker.sock` volume with
  `DOCKER_HOST: "tcp://docker-socket-proxy-rw:2375"` env + a `depends_on` /
  network join so it can resolve the proxy. Drop the volume entirely.
- `roles/pazny.watchtower/defaults/main.yml` — add `watchtower_socket_proxy: true`
  toggle (operator can flip to `false` to fall back to the raw mount on a host where the
  proxy is undesirable; the template branches on it).
- `default.config.yml` — add `docker_socket_proxy_version` is already present (line 1491);
  no new var needed there. If a new toggle surfaces in `default.config.yml`, it MUST use
  stock-Jinja filters + a real default (see §5 risks — stock-Jinja trap).

### cAdvisor + woodpecker-agent — document, do not rewire
- No template change. They land in the gate's reviewed allowlist with their reasons.
- `roles/pazny.woodpecker/templates/compose.yml.j2` — add a 2-line comment above the
  socket mount cross-referencing REM-002 (rootless backend = the real future fix) and the
  new gate's allowlist entry, so the next reader knows the raw mount is *deliberate*, not
  drift.
- `roles/pazny.grafana/templates/compose.yml.j2` — add a 1-line comment above the cAdvisor
  socket mount noting it's allowlisted (`:ro` + privileged + host-path = proxy cosmetic).

### Network plumbing for the new proxy
- `templates/stacks/iiab/docker-compose.yml.j2` — the new `docker-socket-proxy-rw` and
  `watchtower` must share a network. Reuse `iiab_net` (both already on it) OR add a tight
  `socket_proxy_net` if isolation from the rest of `iiab_net` is wanted (preferred: a
  dedicated bridge so only watchtower can reach the rw proxy). Decide during implementation;
  dedicated net is the safer default.

### Docs / queue
- `docs/llm/security/remediation-queue.json` — append a remediation note (NOT a status flip
  to a new ID without the operator; if a REM-id covers "socket-proxy doctrine enforcement,"
  update its `remediation_detail` with the gate + watchtower-rewire evidence). Do not
  fabricate a REM-id.
- `RELEASE.md` (v0.7 section) — one-line pointer once shipped.

---

## 3. Approach (step order)

1. **Write the gate FIRST (red).** Author `test_docker_socket_proxy.py` with the current
   four mounts encoded: proxy-self (sanctioned), cadvisor (ro/allowlisted),
   woodpecker-agent (allowlisted), watchtower (allowlisted *for now*). Run it green against
   today's tree to prove the inventory logic is correct.
2. **Rewire watchtower** through `docker-socket-proxy-rw`. Remove watchtower from the gate
   allowlist so the gate now *requires* the rewire (red), then make it green by dropping the
   raw mount. This is the TDD ratchet — the gate enforces the change can't be reverted.
3. **Add the env-surface assertion** pinning the rw proxy to its minimal verb set and the
   read proxy to its current verbs (no `EXEC` unless `portainer_socket_proxy_can_exec`).
4. **Add the deliberate-mount comments** to woodpecker + grafana templates.
5. **Run the full anatomy suite + `--syntax-check`** (§6). Iterate to green.
6. **Commit** to `feat/v0.7-overnight` (Conventional Commit, surgeon tone). No push.

The change is **render-only + a new gate** — zero live mutation. Watchtower's rewire takes
effect only on the next operator-run playbook, per machinery doctrine.

---

## 4. Gates it needs (`tests/anatomy/test_docker_socket_proxy.py`)

All offline, fast, pure file-scan — no Docker, no live system. Pattern mirrors
`test_image_pin_hygiene.py` (allowlist-with-reasons).

**`test_no_unsanctioned_raw_socket_mounts()`**
- Scan every `roles/pazny.*/templates/*.j2` + `templates/stacks/*/docker-compose.yml.j2`
  for a `- /var/run/docker.sock:` volume line.
- Each hit must be in `SANCTIONED_RAW_MOUNTS = {(file, service): "reason"}`.
- A new raw mount that isn't justified fails. (This is the core invariant.)

**`test_sanctioned_mounts_still_present()`**
- Each `SANCTIONED_RAW_MOUNTS` key must still match a real line — drop the allowlist entry
  once the mount is gone (keeps the allowlist honest, same as
  `test_image_pin_hygiene.test_exceptions_still_apply`). Catches the watchtower entry going
  stale after the rewire.

**`test_socket_proxy_api_surface_is_minimal()`**
- Parse `templates/stacks/infra/docker-compose.yml.j2` (read proxy) and the new
  `docker-socket-proxy-rw` block.
- Assert the read proxy never sets a write verb (`POST`/`EXEC`/`BUILD`/`DISTRIBUTION`)
  to `1` *unconditionally* — they must stay Jinja-gated on `install_portainer` /
  `portainer_socket_proxy_can_*`.
- Assert the rw proxy grants ONLY its allowlisted verb set (no `EXEC`, no `BUILD`).
- Pins the "don't silently widen the Docker API surface" property.

**Optional 4th (defensive):**
**`test_watchtower_uses_socket_proxy()`** — assert `roles/pazny.watchtower/templates/compose.yml.j2`
references `DOCKER_HOST` / `docker-socket-proxy-rw` and carries no raw `docker.sock` volume
when `watchtower_socket_proxy` defaults true. Directly pins the rewire.

Also keep green: the existing `test_image_pin_hygiene.test_no_floating_tags_in_base_stack_templates`
(the new rw-proxy service must pin its image tag — reuse `docker_socket_proxy_version`).

---

## 5. Risks

1. **Watchtower needs more API verbs than the read proxy grants.** Watchtower pulls images
   and *recreates* containers — it needs container create/remove/start/stop + image pull,
   which tecnativa proxy gates behind `POST`/`CONTAINERS`/`IMAGES`. **Mitigation:** verify
   the exact required env flags against watchtower's "Remote Hosts / proxy" docs during
   implementation; do a dry render + a *read-only* live sanity check (`docker inspect` of
   the running watchtower, NOT a restart) to confirm the verb set. If watchtower can't
   function behind the proxy at all, **fall back to keeping its raw mount in the allowlist
   with a documented reason** — the gate (deliverable #1) still ships and is the real win.
   The wiring change is the *nice-to-have*; the enforced invariant is the *must-have*.
2. **Network reachability.** Watchtower (`iiab_net`) must resolve `docker-socket-proxy-rw`.
   Putting both on a dedicated `socket_proxy_net` is cleaner than widening `iiab_net`, but
   adds a network to the iiab base template — verify it doesn't collide with the SEC-02
   gated-net story. **Mitigation:** add the net as a plain internal bridge (`internal: true`
   even — the proxy doesn't need egress), scoped to exactly these two services.
3. **Stock-Jinja vars trap.** Any new var landing in `default.config.yml` /
   `default.credentials.yml` that the core-up plugin loader eager-resolves must use stock
   filters + a real default (`test_config_stock_jinja_only.py`). The watchtower toggle is
   safest as a **role default** (`roles/pazny.watchtower/defaults/main.yml`) — roles render
   during stack-up, after core-up, so they dodge the eager-resolve trap. Do NOT add it to
   `default.config.yml` unless a config-layer override is genuinely needed.
4. **Idempotence churn.** Adding a new compose service to iiab changes the rendered override
   set — confirm a second playbook run reports `changed=0` for the proxy (pinned image, no
   regenerated secret). The proxy has no secret, so this is low-risk.
5. **macOS Docker Desktop socket path.** The proxy still bind-mounts the *real*
   `/var/run/docker.sock` (it's the only sanctioned raw mount); on Docker Desktop that's the
   VM passthrough and already works for the existing infra proxy — no new platform risk.
6. **Over-claiming.** Do NOT mark REM-002 resolved — woodpecker's raw socket stays (the
   real fix is a rootless backend, out of scope). The plan explicitly leaves it allowlisted.

---

## 6. Verification recipe (all read-only / offline)

```bash
cd /Users/pazny/projects/nOS

# 1. New gate + full anatomy suite green
python3 -m pytest tests/anatomy/test_docker_socket_proxy.py -q
python3 -m pytest tests/anatomy/ -q

# 2. Image-pin gate still green (new rw-proxy must pin its tag)
python3 -m pytest tests/anatomy/test_image_pin_hygiene.py -q

# 3. Stock-Jinja gate green (if any var touched default.config.yml)
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q

# 4. Playbook still parses
ansible-playbook main.yml --syntax-check

# 5. Render sanity — confirm watchtower override no longer carries a raw socket mount
#    and references the proxy (dry, no apply):
ansible-playbook main.yml --tags watchtower --check --diff 2>/dev/null | grep -i "docker.sock\|docker-socket-proxy-rw" || true

# 6. Inventory proof — no unsanctioned raw mounts remain outside the allowlist:
grep -rn "/var/run/docker.sock" roles/ templates/stacks/ | grep -v ":ro" | grep -v "docker-socket-proxy"

# 7. (Operator, optional, READ-ONLY live) confirm running watchtower can be rewired —
#    inspect only, never restart:
docker inspect iiab-watchtower-1 --format '{{ '{{ json .Mounts }}' }}' 2>/dev/null || true
```

Expected end state: gate green, suite green, `--syntax-check` clean, watchtower override
free of the raw socket mount (or watchtower allowlisted with a reason if the proxy can't
carry its verb set), woodpecker + cadvisor allowlisted with documented reasons, and the
env-surface assertion pinning the API verbs so nobody can silently widen them.

---

## 7. Definition of done

- [ ] `tests/anatomy/test_docker_socket_proxy.py` lands, suite green.
- [ ] Watchtower routes through `docker-socket-proxy-rw` (raw mount dropped) OR is
      allowlisted with a verified "proxy can't carry its verbs" reason.
- [ ] woodpecker-agent + cadvisor raw mounts carry inline "deliberate, allowlisted" comments.
- [ ] Read-proxy + rw-proxy API surfaces pinned by the env-surface assertion.
- [ ] `ansible-playbook main.yml --syntax-check` clean.
- [ ] Commit on `feat/v0.7-overnight`, Conventional Commit, surgeon-tone body, no push.
- [ ] REM queue note updated (no fabricated REM-id, no false "resolved" on REM-002).
