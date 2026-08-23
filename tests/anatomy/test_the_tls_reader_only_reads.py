"""`tools/tls-uptake.py` measures the transport and can never change it — or
copy the secret it walks past.

WHY THIS IS A GATE. The reader exists because REM-009 was closed on "in-transit
TLS enabled" while REM-217 measured 72 handshakes against 591,811 connections.
The reader is the independent half of every rung of that remediation, so the
temptations are the usual two and one unusual third:

  1. "While it is looking, it could just turn `require_secure_transport` on."
     That is the estate's signature defect — a success marker written by the
     code that attempted the work — and it would make the reader certify its
     own repair. Repair belongs to the playbook.
  2. "A datastore it cannot reach is probably fine." No: unreachable is
     UNKNOWN. `docs/hidden_fees/08` is the STRICT health probe passing an empty
     stack as `0/0 ready`, green for weeks.
  3. THE ONE SPECIFIC TO THIS TOOL. Redis carries its AUTH secret on the
     container's command line — that is REM-217's own remediation (1), a live
     exposure to anything that can `docker inspect`. The reader must READ that
     argv to answer whether a TLS port is configured, and it must not become
     the thing that copies the secret into a log, a JSON blob, or a terminal
     scrollback. Writing this file, the first hand-run of `docker inspect
     --format '{{json .Config.Cmd}}'` put a fragment of that password into a
     session transcript. The mistake is easy, which is why it is gated rather
     than remembered.

WHAT IS PINNED. No write SQL. No mutating docker verb. No filesystem write.
An unreachable source reports UNKNOWN with the reason. Exit 0 whatever it
finds. And — live, when docker is present — the redis secret appears nowhere in
the tool's output in either render.

WHAT IT CANNOT DO. It does not check that the ratios are the RIGHT measure, or
that the verdict thresholds are wise. It checks that the tool cannot lie in the
three directions that would matter: by changing the estate, by reading absence
as health, or by leaking what it inspected.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools/tls-uptake.py"

WRITE_SQL = ("insert ", "update ", "delete ", "drop ", "create ", "alter ",
             "grant ", "revoke ", "set global", "set @@global")

#: `docker <verb>` forms that change something. `exec` and `inspect` are the
#: two the reader is allowed; `exec` is only as safe as the command it carries,
#: which is why the SQL check below is the real guard.
MUTATING_DOCKER = ("start", "stop", "restart", "rm", "kill", "run", "create",
                   "update", "compose", "cp", "commit", "pull", "push")

WRITE_FS = ("open(", "write_text", "write_bytes", "mkdir", "touch", "unlink",
            "rename", "replace", "chmod")


def source() -> str:
    return TOOL.read_text(encoding="utf-8")


def _string_constants() -> list[str]:
    return [n.value for n in ast.walk(ast.parse(source()))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_the_tool_this_gate_describes_exists():
    assert TOOL.is_file(), f"{TOOL} is gone; delete this gate deliberately or restore it"
    assert os.access(TOOL, os.X_OK), "the reader is meant to be run directly"


def test_every_statement_it_sends_is_a_read():
    offenders = []
    for text in _string_constants():
        low = text.lower()
        if not any(k in low for k in ("select ", "show ", "config get")):
            continue
        for verb in WRITE_SQL:
            if verb in low:
                offenders.append(f"{verb.strip()!r} in {text[:70]!r}")
    assert not offenders, (
        "the reader would be changing the very setting it reports on:\n  "
        + "\n  ".join(offenders))


def test_it_never_reaches_for_a_mutating_docker_verb():
    src = source()
    offenders = [v for v in MUTATING_DOCKER
                 if f'"{v}"' in src and f'docker, "{v}"' in src.replace("'", '"')]
    assert not offenders, (
        "a reader that can restart a datastore will eventually be asked to "
        "'just bounce it and re-measure': " + ", ".join(offenders))


def test_it_writes_nothing_to_the_filesystem():
    src = source()
    offenders = [v for v in WRITE_FS if v in src]
    assert not offenders, (
        "the reader must leave no artifact — a cached verdict is a marker, and "
        "a marker written by the measurer is the defect this tool exists for: "
        + ", ".join(offenders))


def test_an_unreachable_datastore_is_unknown_and_never_green():
    """Every branch that gives up must leave `verdict` at its UNKNOWN default
    and record why, rather than falling through to a ratio of nothing."""
    tree = ast.parse(source())
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name in ("mariadb", "postgresql", "redis"):
        fn = fns[name]
        assert '"verdict": "UNKNOWN"' in ast.get_source_segment(source(), fn), (
            f"{name}() must START at UNKNOWN so every early return is honest")
        early = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Return) and isinstance(n.value, ast.Name)]
        assert early, f"{name}() has no early return path — check this gate, not the tool"
    assert '"error"' in source(), "a give-up must carry its reason, not just a verdict"


def test_it_exits_zero_even_when_everything_is_cleartext():
    p = subprocess.run([sys.executable, str(TOOL), "--json"],
                       capture_output=True, text=True, timeout=120, cwd=REPO)
    assert p.returncode == 0, (
        "reporting IS the job; a reader that exited non-zero would be a gate, "
        f"and the ladder REM-217 describes has not been climbed yet\n{p.stderr}")
    report = json.loads(p.stdout)
    assert {d["datastore"] for d in report["datastores"]} == {"mariadb", "postgresql", "redis"}
    for d in report["datastores"]:
        assert d["verdict"] in ("GREEN", "AMBER", "RED", "UNKNOWN")
        if d["verdict"] == "UNKNOWN" and "note" not in d:
            assert d.get("error"), f"{d['datastore']} is UNKNOWN with no reason given"


@pytest.mark.skipif(shutil.which("docker") is None,
                    reason="docker absent — the leak check needs the live container")
def test_the_redis_secret_never_appears_in_the_output():
    """The reader parses an argv that holds the estate's shared redis secret.
    This is the only check that can prove it did not carry it out."""
    probe = subprocess.run(
        ["docker", "inspect", "infra-redis-1", "--format", "{{json .Config.Cmd}}"],
        capture_output=True, text=True, timeout=60)
    if probe.returncode != 0:
        pytest.skip("infra-redis-1 not running — nothing to leak")
    argv = json.loads(probe.stdout or "[]")
    # `--requirepass` and its value are SEPARATE argv entries. The first cut of
    # this check split the flag token and found an empty tail, so it skipped
    # itself with the message "remediation (1) has landed" — a check reporting
    # the fix it was written to wait for. Exactly the shape this suite exists
    # to refuse, and it took two minutes to make.
    secrets = []
    for i, tok in enumerate(argv):
        if not isinstance(tok, str):
            continue
        if tok.strip() == "--requirepass" and i + 1 < len(argv):
            secrets.append(str(argv[i + 1]).strip().strip('"'))
        elif tok.startswith("--requirepass") and len(tok) > len("--requirepass "):
            secrets.append(tok.split("requirepass", 1)[1].strip().strip('"'))
    secrets = [s for s in secrets if len(s) >= 6]
    if not secrets:
        pytest.skip("no secret on the redis command line — remediation (1) has landed")

    for flags in ([], ["--json"]):
        p = subprocess.run([sys.executable, str(TOOL), *flags],
                           capture_output=True, text=True, timeout=120, cwd=REPO)
        blob = p.stdout + p.stderr
        for secret in secrets:
            assert secret not in blob, (
                f"tools/tls-uptake.py {' '.join(flags)} printed the redis AUTH "
                "secret it inspected — the reader became a second copy of the "
                "exposure it reports")
