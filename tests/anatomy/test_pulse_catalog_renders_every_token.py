"""Anatomy gate — no Pulse job may reach Wing carrying an unrendered token.

THE FAILURE, measured live 2026-08-01 on a full converge:

    TASK [pazny.wing] Register discovered Pulse jobs (idempotent upsert)
    Status code was 400 and not [200, 201]

`backup-base/plugin.yml` declared `command: "{{ backup_verify_command }}"`. That
variable exists NOWHERE in the estate — it was invented at authoring time. The
Pulse catalog does a **literal `str.replace`, not a Jinja render**
(`discover-pulse-catalog.py::_build_substitutions`), so an unknown token is not
an error: it passes through verbatim. Wing's SEC-8 validator then rejected
`{{ backup_verify_command }}` as a non-absolute command, and the converge died
at ok=1165 — after 80 changes had already been applied.

WHY NOTHING CAUGHT IT, which is the part worth keeping. There WAS a gate over
these commands (`test_pulse_command_allowlist.py`), and it passed — because the
same commit that introduced the bad token also added

    .replace("{{ backup_verify_command }}", "/Users/pazny/.nos/backup-verify.sh")

to the gate's hand-kept substitution list. The gate was taught an answer
production did not have. That list is now derived from the catalog's real map,
and this file adds the end-to-end check the mirrored list could never make:
**run the actual catalog script and assert nothing `{{ … }}` survives.**

A token is only rendered if it is in the map AND the map's env var is fed by
`roles/pazny.wing/tasks/post.yml`. This asserts the whole chain by executing it.

CI-safe: runs one local Python script, no network, no Docker, no live Wing.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
CATALOG = REPO / "files" / "anatomy" / "scripts" / "discover-pulse-catalog.py"
POST_YML = REPO / "roles" / "pazny.wing" / "tasks" / "post.yml"

TOKEN = re.compile(r"\{\{.*?\}\}")


def _catalog() -> list[dict]:
    """The catalog exactly as post.yml produces it.

    Only NOS_PLAYBOOK_DIR is set. Every other NOS_* is deliberately LEFT UNSET,
    which is the strongest form of the test: a token whose value happens to be
    empty still renders to the empty string, while a token that is not in the
    map at all keeps its braces. Only the second kind fails here.
    """
    env = {**os.environ, "NOS_PLAYBOOK_DIR": str(REPO)}
    out = subprocess.run(
        ["python3", str(CATALOG)], capture_output=True, text=True, env=env, check=True
    ).stdout
    return json.loads(out)


def _unrendered(value) -> list[str]:
    if isinstance(value, str):
        return TOKEN.findall(value)
    if isinstance(value, list):
        return [t for v in value for t in _unrendered(v)]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _unrendered(v)]
    return []


def test_the_catalog_is_not_empty():
    """Guard the guard — an empty catalog passes every assertion below."""
    assert len(_catalog()) > 5, "catalog produced almost nothing; discovery is broken"


def test_no_job_carries_an_unrendered_token():
    offenders = []
    for item in _catalog():
        job = item.get("job", {})
        for field in ("command", "args", "env", "schedule", "runner"):
            for tok in _unrendered(job.get(field)):
                offenders.append(f"{item.get('plugin_name')}:{job.get('name')} {field} -> {tok}")
    assert not offenders, (
        "these reach Wing verbatim and are rejected with a bare 400 mid-converge. "
        "The catalog does a literal str.replace, so an unknown token is silently "
        "passed through — add it to discover-pulse-catalog.py `_build_substitutions` "
        "AND feed its NOS_* env var from roles/pazny.wing/tasks/post.yml:\n  "
        + "\n  ".join(sorted(set(offenders)))
    )


def test_every_mapped_token_is_actually_fed_by_the_playbook():
    """Half a wiring is worse than none: a token in the map whose env var
    nobody sets renders to the empty string — so `command` becomes '' and Wing
    400s just the same, with no clue which token was to blame."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_pulse_catalog", CATALOG)
    mod = importlib.util.module_from_spec(spec)
    os.environ.setdefault("NOS_PLAYBOOK_DIR", str(REPO))
    spec.loader.exec_module(mod)

    src = CATALOG.read_text()
    post = POST_YML.read_text()
    # Env var names the map reads, in map order.
    wanted = set(re.findall(r'_env\("(NOS_[A-Z0-9_]+)"\)', src))
    missing = sorted(v for v in wanted if f"{v}:" not in post)
    assert not missing, (
        "the catalog substitutes these, but pazny.wing/tasks/post.yml never "
        "sets them — they render to '' and the failure gives no name:\n  "
        + "\n  ".join(missing)
    )
