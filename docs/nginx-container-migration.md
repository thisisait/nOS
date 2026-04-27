# Nginx Host → Container Migration — Operator Guide

End-to-end runbook for moving an nOS instance from **host-side nginx**
(Homebrew on macOS, apt on Linux) to the **containerized nginx** that
ships with the `infra` Docker Compose stack.

The repo side is in place (`pazny.nginx_container` role + 52 vhost
templates rewritten to use `nginx_backend_host` + migration recipe
`migrations/2026-05-15-nginx-host-to-container.yml`). What remains is
your `config.yml` flip + a playbook run.

> **Default behaviour is unchanged.** `install_nginx_container: false`
> by default — operators that don't opt in keep running host nginx
> exactly like before. The 52 vhost rewrites use a `default('127.0.0.1')`
> filter, so they're a no-op on the host path.

---

## Why move?

| Host nginx (today) | Containerized nginx (this guide) |
|---|---|
| Brew/apt service outside Docker — separate launchd / systemd unit, separate update cadence | Lives in the same `docker compose -p infra` lifecycle as Authentik / Postgres / Redis |
| `nginx -s reload` on the host; reloads need `sudo` | `docker compose restart nginx` — no sudo |
| Brittle on freshly-imaged Macs (Homebrew formula churn) | Pinned image tag (`nginx:1.27-alpine`) — same byte-for-byte everywhere |
| Linux port (Ubuntu/Debian) needs `apt` + a different vhost path | Identical compose fragment runs on macOS + Linux Docker |
| Logs live in `/opt/homebrew/var/log/nginx/` — fragmented from stack logs | Logs at `~/stacks/infra/nginx/log/` — beside everything else |

The trade-off is the host-loopback round trip: vhosts that previously
proxied to `127.0.0.1:<port>` now go through `nos-host:<port>` (a
`host-gateway` alias). On Docker Desktop this routes through vEthernet;
on Linux Docker through the docker0 bridge. Latency cost is sub-ms in
practice — measured at ~0.2ms on M1.

---

## Phase 0 — Decisions before you flip

| Question | Recommended answer | Why |
|---|---|---|
| Keep brew nginx around as a fallback? | **No** — let the migration `bootout` the plist | Two nginxes can't both bind 80/443. Migration deletes the launchd plist so reboots don't surprise you. |
| Have you got custom files in `/opt/homebrew/etc/nginx/`? | **Inspect first**, then proceed | The playbook re-renders all 52 known vhosts. Custom snippets you added by hand survive — they just live at `~/stacks/infra/nginx/etc/` after the flip. Diff before you flip. |
| Public TLD (`pazny.eu`) or local (`dev.local`)? | **Either is fine** | The container picks up the same cert path the host nginx used. Wildcard LE certs don't care which process serves them. |
| Behind Cloudflare proxy? | **Fine, no change** | CF talks to your public IP; the router still forwards 80/443 to the Mac; the Mac's port mapping just terminates inside the container instead of at brew nginx. |
| Wing / Bone / php-fpm running on the host? | **Make sure they listen on `0.0.0.0`, not `127.0.0.1`** | `nos-host:host-gateway` resolves to a non-loopback address; services bound to loopback only are unreachable from the container. |

---

## Phase 1 — Pre-flip inspection

Run these from your shell **before** you change `config.yml`. They tell
you what state your current host nginx is in and surface anything that
won't migrate cleanly.

```bash
# What brew thinks
brew services list | grep nginx           # expect "nginx started"
ls -la "$(brew --prefix)/etc/nginx/"      # expect nginx.conf, sites-available/, sites-enabled/

# launchd plist that the migration will boot out
ls -la ~/Library/LaunchAgents/homebrew.mxcl.nginx*.plist 2>/dev/null

# Any host-side daemons bound to loopback that the container will need?
sudo lsof -iTCP -sTCP:LISTEN -n -P | grep -E '127\.0\.0\.1:(\d+)'
# If you see Wing FPM (9000), Bone (8200), Hermes, etc., on 127.0.0.1 only,
# you'll need to flip them to 0.0.0.0 — see Phase 4 troubleshooting.

# Custom vhost snippets (anything not under templates/nginx/)
diff -rq /opt/homebrew/etc/nginx/sites-available/ \
         "$(pwd)/templates/nginx/sites-available/" 2>/dev/null \
  | grep -v '\.j2$'
```

If `lsof` shows a service bound to `127.0.0.1` only that's NOT in the
infra/iiab/devops/b2b stacks (which already listen on Docker networks),
fix it before the flip, not after.

---

## Phase 2 — The flip

### 2.1  Edit `config.yml`

```yaml
# config.yml (gitignored)
install_nginx_container: true
install_nginx: false        # mutually exclusive — preflight refuses both
```

### 2.2  Run the playbook

The migration `2026-05-15-nginx-host-to-container` triggers
automatically because it has `applies_if: launchagent_matches:
homebrew.mxcl.nginx*` — i.e. it fires for every host that still has
brew nginx loaded. Severity is `breaking`, so it'll prompt for
confirmation unless you pass `auto_migrate=true`.

```bash
ansible-playbook main.yml -e auto_migrate=true
```

What runs, in order:

1. **Preflight** — fails if both `install_nginx` and
   `install_nginx_container` are true. (You already cleared this in 2.1.)
2. **Migration `nginx_brew_stop`** — `brew services stop nginx`.
3. **Migration `nginx_plist_remove`** — `launchctl bootout` +
   `rm ~/Library/LaunchAgents/homebrew.mxcl.nginx*.plist`. Reboots
   no longer auto-start brew nginx.
4. **Migration `record_nginx_container_marker`** — sets
   `nginx.path = container` in `~/.nos/state.yml` so the framework
   knows you're on the new path.
5. **`pazny.nginx_container` role** — creates `~/stacks/infra/nginx/`
   tree, renders compose override.
6. **`tasks/nginx.yml`** — renders vhosts to `~/stacks/infra/nginx/etc/`
   (NOT `/opt/homebrew/etc/nginx/`). The dual-path `set_fact` at the
   top of `tasks/nginx.yml` picks the destination based on
   `install_nginx_container`.
7. **`docker compose -p infra up --wait`** — nginx joins the infra
   stack alongside Postgres / Authentik / Redis.

Total downtime: **~30s** (brew stop → container up). Migration's
`downtime.estimated_sec: 30` matches reality.

### 2.3  Smoke test

```bash
# Container is up and healthy
docker compose -p infra ps nginx
# Expect: STATUS  Up X minutes (healthy)

# nginx itself answers
curl -I http://localhost/                 # 301 → https://
curl -kI https://wing.dev.local/          # 302 → auth.dev.local

# Container can reach host services via nos-host
docker compose -p infra exec nginx \
  wget -qO- http://nos-host:8200/api/health
# Expect Bone health JSON

# Logs are at the new path
tail -f ~/stacks/infra/nginx/log/access.log
```

If any of the above fail → Phase 4 troubleshooting.

---

## Phase 3 — Post-flip cleanup (optional)

Once you've verified the container path runs clean for a day or two:

```bash
# Remove old brew nginx config tree (keeps the formula installed —
# safer than `brew uninstall`, leaves nothing if you ever flip back)
rm -rf "$(brew --prefix)/etc/nginx/sites-enabled" \
       "$(brew --prefix)/var/log/nginx"

# OR fully uninstall the formula (only if you're sure)
brew uninstall nginx
```

The migration is now dormant — `applies_if.launchagent_matches`
returns false, so re-running the playbook doesn't re-trigger it.

---

## Phase 4 — Troubleshooting

### "502 Bad Gateway" on apps that worked before

The container can't reach the host-side service. Check what it's
bound to:

```bash
sudo lsof -iTCP -sTCP:LISTEN -n -P | grep ':<port>'
# If it shows 127.0.0.1:<port>, it's loopback-only.
```

Fix the service to listen on `0.0.0.0` or use the system loopback alias.
Common offenders + fixes:

| Service | Where to flip | Value |
|---|---|---|
| Wing PHP-FPM (host install, deprecated) | `pazny.wing` defaults | already containerized — flip `install_wing: true` to use the container |
| Bone (host install, deprecated) | `pazny.bone` defaults | already containerized in 2026-04-27+ |
| Custom dev daemons | service-specific | bind to `0.0.0.0` instead of `127.0.0.1` |

### "address already in use" on `docker compose up`

Brew nginx didn't actually stop. Force it:

```bash
sudo lsof -iTCP:443 -sTCP:LISTEN -n -P
# kill the PID, OR:
brew services stop nginx
sudo launchctl bootout gui/$(id -u)/homebrew.mxcl.nginx 2>/dev/null
sudo pkill -9 nginx
```

Then `docker compose -p infra up nginx --force-recreate`.

### Cert errors after the flip

The container reads certs from the same `nginx_container_etc/ssl/`
that vhosts reference via absolute paths. If certs went missing,
they're at the wrong location. Re-render via:

```bash
ansible-playbook main.yml --tags "nginx,acme"
```

### Vhost "host not found in upstream nos-host"

The `extra_hosts: nos-host:host-gateway` line didn't make it into the
override. Re-render the compose:

```bash
ansible-playbook main.yml --tags "infra,nginx_container"
docker compose -p infra up nginx --force-recreate
```

Verify inside the container:

```bash
docker compose -p infra exec nginx getent hosts nos-host
# Expect: <docker host gateway IP>  nos-host
```

### Need to peek at running config

```bash
# nginx -T dumps the full merged config
docker compose -p infra exec nginx nginx -T | less

# Reload after editing a vhost on the host (no sudo!)
docker compose -p infra exec nginx nginx -s reload
```

---

## Recovery / Rollback

If the container path turns out broken and you need to revert:

```yaml
# config.yml
install_nginx: true
install_nginx_container: false
```

Then:

```bash
# Re-install brew nginx if you removed it in Phase 3
brew install nginx
brew services start nginx

# Re-render host configs + start brew service
ansible-playbook main.yml --tags "nginx" -e auto_migrate=false
```

Note: the migration recipe doesn't auto-roll-back (`on_failure:
continue` on every step). The `nginx.path = container` state marker
stays at `container` even after rollback — fix manually:

```bash
yq -i '.nginx.path = "host"' ~/.nos/state.yml
```

---

## Operator checklist (TL;DR — print this)

- [ ] `brew services list | grep nginx` shows brew nginx running
- [ ] `lsof -iTCP -sTCP:LISTEN | grep 127.0.0.1` shows no rogue
      loopback-only services that vhosts proxy to
- [ ] Custom vhost snippets backed up (if any beyond `templates/nginx/`)
- [ ] `config.yml`: `install_nginx_container: true` + `install_nginx: false`
- [ ] `ansible-playbook main.yml -e auto_migrate=true`
- [ ] `docker compose -p infra ps nginx` shows healthy
- [ ] `curl -kI https://wing.<tld>/` returns 302
- [ ] `~/stacks/infra/nginx/log/access.log` exists and grows
- [ ] (Optional, after 1-2 days clean) `brew uninstall nginx`

---

## What changed in the repo (for the curious)

| File | Why |
|---|---|
| `roles/pazny.nginx_container/` (new) | Compose-override role — image, ports, bind mounts, `host-gateway` alias |
| `templates/nginx/sites-available/*.conf` (52 files) | `proxy_pass http://127.0.0.1:` → `proxy_pass http://{{ nginx_backend_host \| default('127.0.0.1') }}:`. Default filter keeps host path identical. |
| `tasks/nginx.yml` | Dual-path render target via `nginx_etc_dir` / `nginx_log_dir` set_fact at top |
| `default.config.yml` | `install_nginx_container: false` flag added |
| `tasks/stacks/core-up.yml` | Wired `pazny.nginx_container` into the infra stack render loop |
| `migrations/2026-05-15-nginx-host-to-container.yml` (new) | Auto-stop + plist-remove + state marker, severity breaking |
