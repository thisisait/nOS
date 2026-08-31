#!/usr/bin/env python3
"""Make a running container read the config the estate rendered for it.

THE GAP THIS CLOSES. Fourteen plugins render config into a running container's
bind mount, and nothing made the process re-read it. `docker compose up -d` is
a no-op when the service DEFINITION is unchanged, so a converge could rewrite
`prometheus.yml` and report `failed=0` while Prometheus kept serving the old
one. Measured 2026-08-31: a Traefik scrape job sat on disk, unread, while every
surface said the converge succeeded. `/-/reload` answers 403 — the lifecycle
API is off on purpose — so a restart is the only lever that exists.

WHY NOT ANSIBLE HANDLERS. Every one of these services already HAS a
`Restart <svc>` handler, and they are notified by the role task that renders
the compose OVERRIDE — not by the plugin loader that renders the CONFIG. That
is the whole defect, and adding fourteen more notify: lines would fix it only
for the run that writes. A config left stale by a previous run, by a converge
whose restart failed, or by a hand edit stays stale forever, because a handler
cannot fire for a change it did not witness. Asking the artifact — file mtime
vs the container's own StartedAt — answers for every writer at any later time,
and it covers a user's own extension without that extension declaring anything.

OPT OUT, DON'T OPT IN. A service is restarted unless its plugin manifest says
it re-reads its own config:

    reload:
      mode: self
      services: [authentik-server, authentik-worker]
      reason: >-
        authentik re-applies /blueprints/custom on a schedule. Measured
        2026-08-31: container up since 08-23, four blueprints carrying
        same-day last_applied timestamps.

That polarity is deliberate. A restart that was not needed costs seconds; a
restart that was needed and did not happen costs an invisible divergence
between the repo and the estate — the failure this whole tool exists for. A
new plugin that declares nothing gets working reload by default.

  tools/reload-stale-config.py              # report only, changes nothing
  tools/reload-stale-config.py --apply      # restart what is stale
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "files/anatomy/plugins"


def _load_reader():
    """Import the sibling reader. It owns the detection; this file owns the act.

    The two are separate files on purpose: `stale-config-status.py` is gated
    read-only (`test_the_stale_config_reader_only_reads.py`), so the thing an
    operator runs to LOOK cannot restart anything by accident.
    """
    path = ROOT / "tools/stale-config-status.py"
    spec = importlib.util.spec_from_file_location("stale_config_status", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def self_reloading_services() -> dict[str, str]:
    """service name → the declared reason it needs no restart."""
    out: dict[str, str] = {}
    for manifest in sorted(PLUGINS.glob("*/plugin.yml")):
        try:
            declared = (yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}).get("reload")
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(declared, dict) or declared.get("mode") != "self":
            continue
        reason = declared.get("reason") or f"declared by {manifest.parent.name}"
        for service in declared.get("services") or []:
            out[service] = " ".join(str(reason).split())
    return out


def _service_of(container: str) -> str:
    """`infra-authentik-worker-1` -> `authentik-worker`.

    Compose names a container `<project>-<service>-<index>`. A service may
    contain dashes, so strip exactly one segment from each end rather than
    splitting and taking the middle — and fall back to the whole name when it
    does not have that shape, since a container the estate did not start is
    still one this tool must not mis-attribute.
    """
    parts = container.split("-")
    if len(parts) >= 3 and parts[-1].isdigit():
        return "-".join(parts[1:-1])
    return container


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="actually restart. Without it this only reports.")
    args = ap.parse_args()

    report = _load_reader().scan()
    if not report["readable"]:
        print(f"UNKNOWN — could not read docker: {report['error']}")
        return 0

    skips = self_reloading_services()
    todo, skipped = {}, {}
    for row in report["stale"]:
        service = _service_of(row["container"])
        if service in skips:
            skipped[row["container"]] = skips[service]
        else:
            todo.setdefault(row["container"], []).append(pathlib.Path(row["source"]).name)

    for container, reason in sorted(skipped.items()):
        print(f"  skip    {container}: {reason}")
    if not todo:
        print("nothing to reload: every mounted config is older than the process that read it.")
        return 0

    for container, files in sorted(todo.items()):
        print(f"  stale   {container}  ({', '.join(sorted(set(files)))})")
    if not args.apply:
        print(f"\n{len(todo)} container(s) would be restarted. Re-run with --apply.")
        return 0

    failed = []
    for container in sorted(todo):
        proc = subprocess.run(["docker", "restart", container],
                              capture_output=True, text=True, timeout=180)
        status = "restarted" if proc.returncode == 0 else "FAILED"
        print(f"  {status:9} {container}"
              + ("" if proc.returncode == 0 else f": {proc.stderr.strip()[:120]}"))
        if proc.returncode != 0:
            failed.append(container)

    # Non-zero ONLY when a restart we attempted did not work. Finding stale
    # config is the normal case this runs for, not an error.
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
