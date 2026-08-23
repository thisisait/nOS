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


#: `occ` subcommands that WRITE. The reader reads Nextcloud's dbdriveroptions
#: through `occ config:system:get`, one keystroke from the verb that would set
#: it — and setting it is precisely the rung this reader is supposed to be
#: independent of. Nothing else in the SQL check would catch `config:system:set`,
#: because it contains no `select` or `show`.
OCC_WRITES = ("config:system:set", "config:system:delete", "config:app:set",
              "db:convert", "maintenance:mode")


def _exec_argv_strings() -> list[str]:
    """Every string the tool actually PASSES to `_exec`, and nothing else.

    The first cut of this check grepped the whole source and failed on the
    tool's own comment explaining that Nextcloud needs `occ config:system:set`
    — a detector reading the description as the fact, which is this repo's most
    repeated gate defect (memory `detectors-must-read-artifacts-not-prose`).
    Argv lists are AST list literals; prose is not.
    """
    out: list[str] = []
    for node in ast.walk(ast.parse(source())):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_exec"):
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    out.append(sub.value)
                elif isinstance(sub, ast.JoinedStr):
                    out.extend(v.value for v in sub.values
                               if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return out


def test_the_nextcloud_read_can_never_become_a_write():
    argv = " ".join(_exec_argv_strings()).lower()
    assert argv, "no _exec call found — check this gate, not the tool"
    offenders = [v for v in OCC_WRITES if v in argv]
    assert not offenders, (
        "the reader would be configuring the client whose configuration it "
        "reports: " + ", ".join(offenders))
    assert "config:system:get" in argv, (
        "the nextcloud leg is gone — restore it or delete this gate "
        "deliberately; nextcloud is the one MariaDB client with no env knob, "
        "so nothing else can say whether it is configured")


def test_a_client_container_that_is_not_running_is_never_reported_as_ok():
    """The five-client table is the part most likely to be skimmed for green
    ticks. A stopped container must read ABSENT — `docs/hidden_fees/08` is this
    estate passing an empty stack as `0/0 ready` for weeks."""
    tree = ast.parse(source())
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "mariadb_clients" in fns, "the per-client reader is gone"
    body = ast.get_source_segment(source(), fns["mariadb_clients"])
    assert '"state": "UNKNOWN"' in body, (
        "each row must START at UNKNOWN so an unhandled path is not a pass")
    assert 'state="ABSENT"' in body, (
        "a container the reader cannot exec into must be ABSENT with its reason")


def test_the_client_table_says_it_is_not_the_effect():
    """It reports DECLARED configuration. MariaDB cannot show another session's
    cipher, so a reader that let this table read as proof would recreate the
    exact defect it was built for — a claim standing in for a measurement."""
    p = subprocess.run([sys.executable, str(TOOL)],
                       capture_output=True, text=True, timeout=180, cwd=REPO)
    assert p.returncode == 0
    out = p.stdout.lower()
    if "mariadb clients" not in out:
        pytest.skip("docker absent — no client table rendered")
    assert "declares" in out or "declared" in out
    assert "not what it negotiated" in out or "declared != encrypted" in out, (
        "the client table must carry its own caveat in the human render, where "
        "it will actually be read")


def test_the_ca_path_the_reader_looks_for_is_the_one_the_playbook_mounts():
    """A reader watching a different path than the renderer writes reports
    every client unconfigured for ever — and is believed, because it is the
    reader. This is the same join the hedgedoc config.json mount needs and the
    reason `CLIENT_CA_PATH` is a module constant rather than five literals."""
    import re

    import yaml
    cfg = yaml.safe_load((REPO / "default.config.yml").read_text(encoding="utf-8")) or {}
    declared = cfg.get("mariadb_client_ca_path")
    if declared is None:
        pytest.skip("mariadb_client_ca_path not declared yet — rung 3 unstarted")
    m = re.search(r'^CLIENT_CA_PATH\s*=\s*"([^"]+)"', source(), re.M)
    assert m, "CLIENT_CA_PATH is no longer a plain module constant"
    assert m.group(1) == declared, (
        f"the reader looks at {m.group(1)} and the playbook mounts {declared}")
