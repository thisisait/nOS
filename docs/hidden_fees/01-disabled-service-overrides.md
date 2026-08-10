# 01 — A disabled service's compose override lingers on the host

## The fee

The role render path is **create-only**. Each role writes
`{{ stacks_dir }}/<stack>/overrides/<svc>.yml`, and the orchestrators merge
whatever `ansible.builtin.find` turns up — but nothing ever removes a fragment.

Two cases, and only one is closed:

- **Retired** (the service is gone from nOS) — closed 2026-07-20 by
  `nos_retired_services` + `tasks/stacks/prune-retired.yml`.
- **Disabled** (`install_<svc>: false`, the service still ships) — **open.** The
  fragment stays on disk and keeps being merged into `docker compose up`, so a
  service the operator switched off can keep its config alive, and in some shapes
  keep running, until something else recreates the stack.

The asymmetry is the fee: we fixed the case that failed loudly and left the case
that does not fail at all.

## The number, measured 2026-08-10

**Sixteen.** `tools/discovery-scan.py` gained a probe for this (probe E) and
found sixteen services carrying `install_<svc>: false` with a container up:

`bookstack · code_server · firefly · gitlab · hedgedoc · homeassistant ·
influxdb · jellyfin · miniflux · nodered · ntfy · onlyoffice · qgis_server ·
smtp_stalwart · snappymail · wordpress`

Two classes are deliberately NOT counted, because comparing them would be a
guess rather than a contradiction: flags `main.yml` auto-enables from other
flags at run time (`install_postgresql`, `install_mariadb`), and Tier-2 manifest
apps whose bring-up belongs to `apps/<name>.yml` rather than to a toggle
(`qdrant`). The probe derives both lists rather than restating them.

## What it costs beyond tidiness

Nine rows in the remediation queue argue mitigation from exactly this flag —
*"MITIGATED: install_gitlab=false"* — and three of those are **HIGH**
(REM-159 gitlab, REM-165 erpnext, REM-184 qgis_server). `gitlab` and
`qgis_server` are in the list above.

A row that lowers its own severity because a service is "disabled" is worse than
an untouched open row: it is an open exposure that has been *talked out of being
counted*. The fee is therefore not only a stale container — it is a queue whose
arithmetic is wrong in the reassuring direction.

## When the bill comes due

Whenever a service is toggled off on a host that has already converged with it
on. The failure is not an error — it is a container or a config that is still
there after the operator believes they removed it, discovered later by someone
wondering why a disabled service is answering.

It also compounds with the blank allowlist gap: a disabled service's *data* is
not wiped either, so the next enable resurrects a half-old state.

## How it was found

Sideways. Puter's removal left `puter.yml` + `puter-base.yml` behind and failed
the whole `iiab` stack (`unable to prepare context: path .../files/puter not
found`). Fixing the retired case made the disabled case visible by contrast — it
was never reported by anything.

## What closes it

The managed-resource manifest in
[`docs/archive/blank-uninstall-managed-resources.md`](../archive/blank-uninstall-managed-resources.md)
(P1.5): a declared inventory of what a service owns — override fragments, data
dirs, routes, Authentik objects — so disable and remove both become
*reconciliation* rather than "stop writing new files".

Deliberately **not** solved by "prune any override without a matching role": that
heuristic eats legitimate fragments with no 1:1 role, e.g. the apps_runner's
merged `auto.yml`.
