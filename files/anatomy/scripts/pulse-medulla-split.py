#!/usr/bin/env python3
"""Refuse a medulla job set the medulla cannot fire. stdin: discover-pulse-catalog.py's JSON;
env PULSE_MEDULLA_JOBS: the comma-separated ids. Exit 1 with one line per refused id.

The Python daemon skips exactly this set, so a job the medulla refuses (a `secret:` env, a
runner but subprocess: medulla/src/pulse/mod.rs::fire) would be fired by nobody. Prints key
names, never values. Gate: tests/anatomy/test_the_medullas_jobs_are_ones_it_can_fire.py.
"""

from __future__ import annotations

import json
import os
import sys


def refusals(catalog: list[dict], ids: list[str]) -> list[str]:
    jobs = {f"{e['plugin_name'].removesuffix('-base')}:{e['job']['name']}": e["job"] for e in catalog if "job" in e}
    out = []
    for jid in ids:
        job = jobs.get(jid)
        if job is None:
            out.append(f"{jid}: no such job in the Pulse catalog")
            continue
        if (job.get("runner") or "subprocess") != "subprocess":
            out.append(f"{jid}: runner {job['runner']} — the medulla fires subprocess jobs only")
        env = job.get("env") or {}
        secret = sorted(k for k, v in (env.items() if isinstance(env, dict) else []) if str(v).startswith("secret:"))
        if secret:
            out.append(f"{jid}: env {', '.join(secret)} is a secret: reference — the medulla does not read secrets.yml")
    return out


def main() -> int:
    ids = [j for j in os.environ.get("PULSE_MEDULLA_JOBS", "").split(",") if j]
    bad = refusals(json.load(sys.stdin), ids) if ids else []
    for line in bad:
        print(line)
    if bad:
        print("pulse_medulla_jobs names job(s) the medulla cannot fire; take them out of config.yml.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
