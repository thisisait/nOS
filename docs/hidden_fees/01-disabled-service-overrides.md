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

## The number, measured 2026-08-10 — and corrected the same day

The first measurement said **sixteen**, and it was taken on the wrong config
layer. Probe E of `tools/discovery-scan.py` read `install_<svc>: false` from
`default.config.yml` alone — the committed default — but this host's
`config.yml` (the documented override layer, which wins) sets every one of
those sixteen flags to `true`. Those services run because they are **enabled**;
committed-default-vs-estate is expected drift for every config.yml-enabled
service, not a contradiction.

Resolved across both layers, the measured number is **one**: the operator's
config.yml sets `install_mailpit: false`, `mailpit.yml` + `mailpit-base.yml`
are still under `~/stacks/iiab/overrides/`, and `iiab-mailpit-1` is up and
healthy — the mechanism exactly as described, with one victim, not sixteen.
The probe now resolves the layering (`resolved_install_flags()`:
default.config.yml, then config.yml when present; gate
`tests/anatomy/test_discovery_probe_reads_resolved_config.py`).

Two classes are deliberately NOT counted, because comparing them would be a
guess rather than a contradiction: flags `main.yml` auto-enables from other
flags at run time (`install_postgresql`, `install_mariadb`), and Tier-2 manifest
apps whose bring-up belongs to `apps/<name>.yml` rather than to a toggle
(`qdrant`). The probe derives both lists rather than restating them.

## What it costs beyond tidiness

Nine rows in the remediation queue argue mitigation from exactly this flag —
*"MITIGATED: install_gitlab=false"* — and three of those are **HIGH**
(REM-159 gitlab, REM-165 erpnext, REM-184 qgis_server). Those claims commit the
same wrong-layer error in the *reassuring* direction: they read `false` off the
committed default while the operator's config.yml enables the service, so
gitlab and qgis_server are up — not as zombies, but because they were never
switched off. Their amended dispositions ("treat as fully exposed") are
therefore right in conclusion, and a flag on either layer is not evidence:
only the reconciled estate is.

A row that lowers its own severity because a service is "disabled" is worse than
an untouched open row: it is an open exposure that has been *talked out of being
counted*. The fee is therefore not only a stale container — it is a queue whose
arithmetic is wrong in the reassuring direction.

## Status — reconciler shipped 2026-08-10, removal opt-in

`tasks/stacks/prune-disabled.yml` is the disabled half of `prune-retired.yml`,
imported by both orchestrators. It **reports every converge** (that alone ends
the "does not fail loudly" complaint) and **removes on `prune_disabled_overrides:
true`**, default false — destructive teardown waits for an explicit token, per
the estate's destructive-op doctrine.

The verification number needed correcting too. "32 fragments across 18
services" was computed with default-only semantics — semantics the shipped
task does not use: it resolves each flag via `lookup('vars', …)`, so the
operator's config.yml counts, exactly as its own comment says. Under the
semantics that actually run, this host reports **2 fragments across 1 service**
(`mailpit.yml` + `mailpit-base.yml`), and `postgresql` is correctly absent
under either reading. The reconciler was right all along; the narrative around
it was measured on the wrong layer.

Two exclusion classes are DERIVED rather than listed, so neither needs an edit
when the estate grows: flags `main.yml` auto-enables from other flags
(`install_postgresql`, `install_mariadb` — pruning postgresql's fragment would
tear down the database), and Tier-2 manifest apps owned by `apps/<name>.yml`.
Matching is separator-insensitive: `code-server.yml` sits beside
`qgis_server.yml`, and a hyphen-only mapping silently misses the
underscore-named fragments.

**This entry closes when the default flips to true.** That is a dated obligation
on an operator who has seen the list, not a permanent shim. Gate:
`tests/anatomy/test_disabled_services_are_reconciled.py`.

REM-159 (HIGH, gitlab), REM-184 (HIGH) and REM-185 (MEDIUM, qgis_server) carry an
amended disposition: exposure stands, but the mechanism is the wrong-layer read
above — the operator's config.yml enables those services, so their containers
are up legitimately and the original `install_*=false` mitigation claims read a
layer the estate does not run. REM-165 (erpnext) was left alone — its container
genuinely is not running, so its claim holds.

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
