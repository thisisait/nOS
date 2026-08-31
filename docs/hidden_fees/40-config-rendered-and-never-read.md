# 40 — Config rendered, converge green, process still on the old one

**Found 2026-08-31, while adding a Prometheus scrape job that never appeared.**

Fourteen plugins render configuration into the bind mount of a **running**
container. Nothing made any of those processes re-read it.

The converge does its half correctly: the plugin loader's `pre_compose` hook
renders the file, the file lands, `docker compose up -d` runs, and the play
recap says `failed=0`. But `compose up -d` is a no-op when the service
*definition* is unchanged — a mounted file's content is not part of that
definition — so the container is never recreated and the process goes on
serving whatever it read at startup.

```
$ grep -A2 "job_name: traefik" ~/stacks/observability/prometheus/prometheus.yml
  - job_name: traefik            # rendered, on disk, correct
$ curl -s localhost:9090/api/v1/targets | grep traefik
                                 # absent
$ curl -X POST localhost:9090/-/reload
403                              # lifecycle API off, on purpose
```

## Why nobody caught it

Every one of these services **already has** a `Restart <svc>` handler. They are
notified by the role task that renders the compose *override* — never by the
plugin loader that renders the *config*. So the machinery is present and the
wire to it is not, which is the shape that survives review: a reader greps for
`Restart prometheus`, finds it, and moves on.

The affected set is the whole observability spine plus SSO — `prometheus`,
`loki`, `tempo`, `grafana` and its five composition plugins, `authentik`, and
the four `alloy-*` fragments.

## When the bill comes due

It has been coming due continuously, silently, for as long as the pattern has
existed. Every converge that changes a scrape target, a retention window, a
Loki limit, a Grafana datasource or an alert rule reports success and changes
nothing until something unrelated restarts the container. The gap between "the
repo says X" and "the process is running X" is invisible from both ends: the
repo is right, the container is healthy, and no surface compares them.

The sharp edge is that a restart *does* eventually happen — a reboot, an image
bump, a blank — so the config silently becomes live at an unrelated moment,
attributing its effects to whatever change was actually being made that day.

## How it was found

Sideways. A Traefik scrape job was added, the converge finished `failed=0`, and
the target simply was not there. The first assumption was a bad job definition;
the file on disk was correct, which is what made it interesting.

## What closes it

`tools/stale-config-status.py` (reader) and `tools/reload-stale-config.py`
(actor), wired into `main.yml` after stack-up. The detection is derived, not
declared: a read-only bind mount under `stacks_dir` whose mtime is newer than
the container's own `StartedAt` is a process running replaced config. That
covers a plugin nobody has written yet, including a user's own extension.

A handler could not have done this. It fires only for a change it witnessed, so
config left stale by a previous run, by a converge whose restart failed, or by a
hand edit stays stale forever. Asking the artifact answers for every writer at
any later time.

Opt-out is declared in the plugin manifest and must carry its evidence:

```yaml
reload:
  mode: self
  services: [authentik-server, authentik-worker]
  reason: >-
    authentik re-applies /blueprints/custom on a schedule; measured
    2026-08-31 with the container up since 08-23 and four blueprints
    applied same-day.
```

Gate: `test_rendered_config_reaches_the_process.py`.

## What is still owed

- **The host organs are not covered.** The reader only sees containers.
  Wing, Bone, Pulse and cortex read their config at launchd start, and nothing
  compares a rendered file against a daemon's start time.
- **Restart is the only lever.** Several of these services can reload in place
  (`SIGHUP`, a lifecycle endpoint) and a restart is a blunt substitute — cheap
  here, not obviously cheap on a busier estate.
