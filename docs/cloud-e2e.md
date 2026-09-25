# Cloud e2e — testing nOS inside a Claude cloud session

**What this is:** the runbook for proving nOS end to end inside a disposable
Linux sandbox — specifically Claude Code on the web (claude.ai/code), where
every session is a fresh Ubuntu 24.04 container. The adapter lives in
`tools/cloud/`; the SessionStart hook (`.claude/hooks/session-start.sh`) runs
its bootstrap automatically.

**What this is not:** a replacement for the operator's Mac or the
`Integration (ubuntu-24.04)` CI job. It is a third lane with one property the
other two lack: an agent can run it, read the verdict, fix, and re-run inside
one conversation.

## TL;DR

```bash
# Automatic in a cloud session (SessionStart hook). By hand:
tools/cloud/bootstrap.sh          # toolchain + dockerd, idempotent (~20 s warm)
. tools/cloud/env.sh              # frozen venv on PATH, distro module python

tools/cloud/e2e.sh static         # syntax-check + full pytest suite   (~5 min)
tools/cloud/e2e.sh preflight      # can every image the profile needs be pulled?
tools/cloud/e2e.sh converge       # ansible-playbook main.yml -e @profiles/cloud-e2e.yml
tools/cloud/e2e.sh smoke          # nos-smoke --strict against what converged
tools/cloud/e2e.sh idempotence    # second converge must be changed=0
tools/cloud/e2e.sh all            # the five above, stop at first red
tools/cloud/e2e.sh reset          # wipe containers/volumes/stacks (sandbox only)
```

Every tier prints one `[e2e] PASS|FAIL <tier> …` verdict line and writes its
full log to `~/.nos/e2e/<tier>.log`. Extra arguments go to ansible:
`tools/cloud/e2e.sh converge -e install_gitea=true`. Another profile:
`NOS_E2E_PROFILE=profiles/dev-minimal.yml tools/cloud/e2e.sh converge`.

## The sandbox, measured (2026-09-25)

| Fact | Consequence | Where it is handled |
|---|---|---|
| Ubuntu 24.04, root, 4 vCPU / 16 GB, PID 1 is `process_api` — **no systemd** | `systemctl`, `systemctl --user`, `loginctl` all fail | `nos_init: none` → `nos-proc` (§No init system) |
| `docker` + `dockerd` binaries present, daemon **not running** | nothing answers on the socket | `bootstrap.sh` starts `dockerd` detached |
| `$USER` **unset** | `ansible_facts['env']['USER']` aborted the run | facts `user_id` / `user_gid` (gated) |
| `/usr/bin/python3` → 3.11 via alternatives; `python3-apt` is built for **3.12** | every `apt:` task fails on the venv python | `env.sh` picks the python that imports `apt_pkg` |
| stdout/stderr of the agent's shell are **non-blocking** | `ansible` refuses to start ("requires blocking IO") | `e2e.sh` writes every run to a log file |
| egress via a policy proxy: Docker Hub, GitHub, PyPI, apt, packagist **open**; `galaxy.ansible.com`, ghcr **blob storage** (`pkg-containers.githubusercontent.com`), `quay.io`, `lscr.io` **403** | collections and ~11 images unreachable | §Registries, §Galaxy |
| egress IP is **shared** — Docker Hub anonymous budget measured 24/100 before the first pull | pulls fail with `toomanyrequests` | `mirror.gcr.io` registry mirror |

## No init system

`tasks/_platform.yml` now derives `nos_init` (`launchd` | `systemd` | `none`)
from `ansible_facts['service_mgr']`, and `nos_user_systemctl` — the command
every call site uses to control a user unit (`systemctl --user` on a systemd
host, `~/.local/bin/nos-proc` otherwise).

The **unit contract does not fork.** `pazny.linux.systemd_user::ensure_unit`
renders the same `~/.config/systemd/user/<name>.service` either way; on a
`none` host it installs `files/anatomy/scripts/nos-proc.py` and asks it to
start the unit. nos-proc honours `ExecStart`, `WorkingDirectory`,
`Environment`, `EnvironmentFile`, `Type=oneshot`, `Restart`, `RestartSec`,
accepts systemctl-style flags (`enable --now`, `disable --now`), and keeps
`~/.nos/proc/<unit>.{pid,log}`.

What it does **not** do, by design and out loud:

- **Timers are not scheduled.** `nos-proc start x.timer` prints
  `NOT-SCHEDULED` and exits 0 — absent, never green. Pulse's own scheduler
  still runs; only systemd-timer jobs (backup, heartbeat) are inert.
- **No boot persistence.** A resumed session has no daemons until
  `tools/cloud/e2e.sh converge` (or `nos-proc start <unit>`).
- **No ordering.** `After=`/`Wants=` are ignored.

Docker: `pazny.linux.docker` skips `systemctl start docker` when
`nos_init == 'none'` and relies on its existing `docker info` verify step —
`bootstrap.sh` owns `dockerd`'s lifetime there.

Gate: `tests/anatomy/test_nos_proc_runs_the_unit_contract.py` (runs a real
process; also refuses any raw `systemctl --user` outside the library).

## Registries

`tools/cloud/registry-reach.py` answers "can this sandbox pull what the
profile runs?" in seconds, before a converge answers it in forty minutes.
It resolves the enabled services from `state/manifest.yml` `install_flag`s,
renders each role's `templates/compose*.j2` `image:` lines against role
defaults + config + profile + `-e`, and probes each image with a manifest
**HEAD** (HEADs do not spend Docker Hub's anonymous budget; `docker manifest
inspect` GETs do) plus a CONNECT to the registry's blob host — ghcr.io
answers while its blob host is refused, so a manifest check alone lies.

```text
registries: docker.io 48/49, gcr.io 1/1, ghcr.io 0/6, lscr.io 0/3, quay.io 0/1
```

Unreachable under the default cloud policy (`--all`, 2026-09-25): authentik
(ghcr), bluesky_pds, kiwix, mcp_gateway, open_webui, paperclip (ghcr),
bookstack, calibre_web, code_server (lscr), hedgedoc (quay). Two ways out:

1. **Same image, reachable registry.** Upstream authentik publishes identical
   images to Docker Hub as `authentik/server`; `authentik_image` (role
   default `ghcr.io/goauthentik/server`) is the knob, and the cloud profile
   flips it. Repeat per role when a service joins the profile.
2. **Widen the environment's network policy** (environment settings →
   Network access): allow `pkg-containers.githubusercontent.com`, `quay.io`,
   `cdn01.quay.io`, `lscr.io`, `galaxy.ansible.com`. That is the operator's
   decision, not the repo's.

`bootstrap.sh` writes `/etc/docker/daemon.json` with
`"registry-mirrors": ["https://mirror.gcr.io"]` **only when no daemon.json
exists** — Google's public pull-through cache of Docker Hub, which takes the
shared-IP rate limit out of the picture.

Gate: `test_cloud_e2e_contract.py::test_profile_pulls_nothing_the_sandbox_refuses`.

## Galaxy

`galaxy.ansible.com` is refused, GitHub is not. `tools/ci-local.sh` probes
Galaxy (`tools/cloud/galaxy-install.py --probe`) and, when refused, installs
**the same pins** from `requirements.lock.yml` via git, using
`tools/cloud/galaxy-git-sources.yml` for the URLs. Every git install is
`--no-deps` (resolving `dependencies:` would call Galaxy); the lock plus the
`deps:` rows are the complete closure. `geerlingguy.mac` reports `1.2.0` from
git at tag `5.0.0` — its repo's `galaxy.yml` is stale; the tag is the pin.

Gates: `test_every_lock_pin_has_a_git_source`,
`test_git_install_plan_never_asks_galaxy_for_dependencies`.

## The controller venv must stay off the playbook's PATH

Measured on the first cloud converge: with `.ci-venv/bin` first on `PATH`, the
playbook's own `Install global Pip packages.` task (`tasks/extra-packages.yml`,
a bare `pip3 install`) installed `ansible` **into the frozen controller venv**
and moved ansible-core 2.21.0 → 2.21.4 mid-run, silently (`failed_when:
false`). `e2e.sh` therefore runs `.ci-venv/bin/ansible-playbook` by absolute
path with the venv stripped from `PATH`, the cloud profile sets
`pip_packages: []`, and `bootstrap.sh` rebuilds a venv whose ansible-core no
longer equals `tools/ci-freeze.env`. The CI Integration jobs have the same
shape (venv on `$GITHUB_PATH`, `ansible` in `tests/config.yml`'s
`pip_packages`) — filed as a follow-up, not changed here.

## The profile

`profiles/cloud-e2e.yml` — the smallest estate that still proves the
topology: L0 (PostgreSQL, Redis), Authentik, Traefik as the edge. Every
host-only macOS concern is off; so is every service whose image the default
policy refuses. Grow it one service at a time, running `preflight` first.

## Status

<!-- CONVERGE-STATUS -->
