#!/usr/bin/env python3
"""Emit GDPR Article-30 records as a JSON array (machine-readable sibling of
the human DPA register).

`roles/pazny.wing/tasks/post.yml` runs this to ingest the per-plugin `gdpr:`
blocks into Wing's live `gdpr_processing` table — one `php bin/upsert-gdpr.php
--json=-` over the whole array — giving the `/gdpr` UI parity with the static
`state/dpa-register.md`. Both surfaces share the canonical mapper in
`files/anatomy/module_utils/nos_gdpr.py`, so they never diverge.

Usage:
  python3 tools/gdpr-records.py --tier core    # Tier-1 plugins  (svc_*)
  python3 tools/gdpr-records.py --tier app      # app manifests (app_*)
  python3 tools/gdpr-records.py --tier all      # plugins, apps, agents, importers
  python3 tools/gdpr-records.py --tier host --resolved  # plugins + agents as THIS host
                                                        # serves them (Wing's live rows)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "files/anatomy"))
from module_utils import nos_gdpr  # noqa: E401


def _choices() -> tuple[dict, dict]:
    """The host's choices through every layer (config.yml wins), as job_readiness reads them."""
    import yaml
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity
    backends = yaml.safe_load((REPO / "state/habitat/llm-backends.yml").read_text())["backends"]
    flags = {r["enabled_flag"] for r in backends.values() if r.get("enabled_flag")}
    cfg = nos_identity.resolved({"iris_backend", "agents_backend", "gdpr_posture", "install_ollama", *flags})
    on = lambda v: str(v).strip().lower() in ("true", "yes", "1")  # noqa: E731
    armed = {k for k, r in backends.items() if r.get("enabled_flag") and on(cfg.get(r["enabled_flag"]))}
    if not on(cfg.get("install_ollama")):
        armed.discard("ollama")  # the thalamus arms ollama only with its daemon installed
    return {"armed": armed, "cells": {"iris": str(cfg.get("iris_backend") or "").strip()},
            "agents_backend": str(cfg.get("agents_backend") or "").strip(),
            "posture": str(cfg.get("gdpr_posture") or "standard"),
            "flags": nos_identity.install_flags()}, backends


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", choices=["core", "app", "agent", "host", "all"], default="core")
    ap.add_argument("--resolved", action="store_true",
                    help="agent records as this host's config serves them (nos_gdpr.effective_records)")
    args = ap.parse_args()

    if args.tier == "core":
        recs = nos_gdpr.records_from_plugins(REPO / "files/anatomy/plugins")
    elif args.tier == "app":
        recs = nos_gdpr.records_from_app_manifests(REPO / "apps")
    elif args.tier == "agent":
        recs = nos_gdpr.records_from_agents(REPO / "files/anatomy/agents")
    elif args.tier == "host":
        recs = nos_gdpr.records_from_plugins(REPO / "files/anatomy/plugins")
        recs += nos_gdpr.records_from_agents(REPO / "files/anatomy/agents")
    else:
        recs = nos_gdpr.all_records(REPO)
    if args.resolved:
        recs = nos_gdpr.effective_records(recs, *_choices())

    json.dump(recs, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
