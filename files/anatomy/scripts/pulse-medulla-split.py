#!/usr/bin/env python3
"""Refuse a medulla job set the medulla cannot fire. stdin: discover-pulse-catalog.py's JSON;
env PULSE_MEDULLA_JOBS: the comma-separated ids. Exit 1 with one line per refused id.

The Python daemon skips exactly this set, so a job the medulla refuses (a `secret:` env, a
runner but subprocess: medulla/src/pulse/mod.rs::fire) would be fired by nobody. A script that
opens secrets.yml / credentials.yml itself is a `secret:` env in disguise, refused the same.
Prints key names, never values. Gates: tests/anatomy/test_the_medullas_jobs_are_ones_it_can_fire.py,
tests/anatomy/test_no_pulse_job_reads_the_secret_store.py.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pulse"))
from pulse import secrets  # noqa: E402 — the one secret: parser (test_secret_resolution_is_shared)

STORE = re.compile(r"(?<![\w.])(secrets|credentials)\.yml")
_DOC_HOLDERS = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def reads_store(path: str) -> bool:
    """Code in this script, not a comment or a docstring, names the secret store."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return False
    if b"\0" in raw[:1024]:
        return False  # a binary on the command line (python3, bash): not a script to scan
    text = raw.decode("utf-8", "replace")
    if path.endswith(".py") or re.match(r"#!.*python", text):
        tree = ast.parse(text)
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, _DOC_HOLDERS) and n.body and isinstance(n.body[0], ast.Expr)}
        return any(isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
                   and STORE.search(n.value) for n in ast.walk(tree))
    return any(STORE.search(line.split("#", 1)[0]) for line in text.splitlines())


def store_readers(job: dict) -> list[str]:
    """The scripts on a job's command line that open the secret store themselves."""
    words = [job.get("command") or "", *[a for a in job.get("args") or [] if isinstance(a, str)]]
    return [t for w in words for t in w.split() if os.path.isfile(t) and reads_store(t)]


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
        secret = sorted(secrets.refs(env if isinstance(env, dict) else {}))
        if secret:
            out.append(f"{jid}: env {', '.join(secret)} is a secret: reference — the medulla does not read secrets.yml")
        for path in store_readers(job):
            out.append(f"{jid}: {os.path.basename(path)} reads the secret store itself — give it a secret: env instead")
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
