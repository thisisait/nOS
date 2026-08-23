#!/usr/bin/env python3
"""How much of the datastore traffic on this estate is actually encrypted.

WHY THIS EXISTS. REM-009 is marked RESOLVED in the security queue on the
strength of "in-transit TLS enabled". It IS enabled. MariaDB negotiates
TLS_AES_256_GCM_SHA384 to any client that asks, PostgreSQL runs `ssl=on`. And
REM-217 measured, on 2026-08-22, that essentially nothing asks: 72 TLS
handshakes against 591,811 connections on MariaDB, and 23 of 42 PostgreSQL
backends in cleartext — including Infisical, the secrets vault, and 20 of
Authentik's.

That is the estate's oldest defect wearing a transport-layer hat: **the code
that enabled TLS reported its own success, and nothing ever read the effect.**
CLAUDE.md already states the division of labour — pytest owns the SHAPE,
`--tags verify` owns the EFFECT, `nos-smoke --strict` owns end-to-end truth.
A shape gate would have passed this estate every day for months, because the
shape was correct the whole time.

So this is the effect half, and it exists BEFORE the fixes rather than after,
so that each rung of REM-217 is verified by something that is not the rung.

WHAT IT IS NOT. It reads. It does not enable TLS, restart anything, or write a
marker. Every statement it issues is a SELECT or a `CONFIG`-free inspect, and
`tests/anatomy/test_the_tls_reader_only_reads.py` pins that.

WHAT IT REFUSES TO GUESS.
  * A datastore it cannot reach is UNKNOWN, never green. "No data" and "no
    problem" are the two readings this estate has most often confused.
  * A **unix-socket** PostgreSQL session is not a cleartext flow on the docker
    fabric and is never counted as one. The original REM-217 measurement of
    "23 of 42 plaintext" includes the measuring session itself.
  * MariaDB's ratio is CUMULATIVE SINCE THE SERVER STARTED. It cannot fall
    quickly even after every client is fixed, so the reader prints uptime
    beside it and says what the number is. Judge a fix by the trend across two
    reads, or by restarting the counter, not by one absolute number.
  * Redis is reported from its LISTENER, because with `tls-port 0` there is no
    TLS listener and therefore provably zero encrypted sessions — a shape read
    that determines the effect. If a TLS port ever IS configured, the per-
    session split becomes genuinely unknown from outside and says so.

Usage:
    tools/tls-uptake.py            # one block per datastore
    tools/tls-uptake.py --json     # for a caller

Exit 0 always, including when everything is cleartext. Reporting is the job;
a reader that exited non-zero would be a gate, and this one cannot be a gate
until the estate has climbed the ladder REM-217 describes.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

MARIADB = "infra-mariadb-1"
POSTGRES = "infra-postgresql-1"
REDIS = "infra-redis-1"

TIMEOUT = 20


def _docker() -> str | None:
    return shutil.which("docker")


def _exec(container: str, argv: list[str]) -> tuple[int, str, str]:
    docker = _docker()
    if not docker:
        return 127, "", "docker not on PATH"
    try:
        p = subprocess.run([docker, "exec", container, *argv],
                           capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {TIMEOUT}s"
    except OSError as exc:                                  # pragma: no cover
        return 126, "", str(exc)
    return p.returncode, p.stdout, p.stderr.strip()


def mariadb() -> dict:
    """Cumulative TLS uptake. The counters are the only per-connection record
    MariaDB keeps; `performance_schema` is OFF on this build, so there is no
    per-session cipher view to fall back on."""
    out = {"datastore": "mariadb", "container": MARIADB, "verdict": "UNKNOWN"}
    # The root password never leaves the container: `sh -c` expands the env var
    # inside, so it appears on no host argv and in no process list here.
    sql = ("select variable_name, variable_value from information_schema.global_status "
           "where variable_name in ('CONNECTIONS','SSL_ACCEPTS','THREADS_CONNECTED','UPTIME'); "
           "select 'REQUIRE_SECURE_TRANSPORT', @@require_secure_transport")
    rc, stdout, stderr = _exec(
        MARIADB, ["sh", "-c", f'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -N -B -e "{sql}"'])
    if rc != 0:
        out["error"] = stderr or f"exit {rc}"
        return out

    vals = {}
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 2:
            try:
                vals[parts[0].strip().upper()] = int(parts[1])
            except ValueError:
                pass
    if "CONNECTIONS" not in vals or "SSL_ACCEPTS" not in vals:
        out["error"] = "counters missing from global_status"
        return out

    total, tls = vals["CONNECTIONS"], vals["SSL_ACCEPTS"]
    # The ratio alone can never certify the end state: it is cumulative, so a
    # perfect cutover today still reads ~0% against a year of plaintext. The
    # switch CAN certify it — with require_secure_transport ON the server
    # refuses a plaintext connection, so no unencrypted session exists to count.
    required = bool(vals.get("REQUIRE_SECURE_TRANSPORT"))
    out.update(
        connections=total,
        ssl_accepts=tls,
        threads_connected=vals.get("THREADS_CONNECTED"),
        uptime_seconds=vals.get("UPTIME"),
        require_secure_transport=required,
        encrypted_ratio=(tls / total) if total else None,
        basis="cumulative since server start; the switch is what certifies the end state",
        verdict="GREEN" if required else "AMBER" if tls else "RED",
    )
    return out


def postgresql() -> dict:
    """Per-backend, live. `pg_stat_ssl` is the honest source: it reports what
    each session NEGOTIATED, not what the server offers."""
    out = {"datastore": "postgresql", "container": POSTGRES, "verdict": "UNKNOWN"}
    sql = ("select coalesce(host(a.client_addr),'local'), a.usename, s.ssl, count(*) "
           "from pg_stat_ssl s join pg_stat_activity a using(pid) group by 1,2,3")
    rc, stdout, stderr = _exec(POSTGRES, ["psql", "-U", "postgres", "-tAF|", "-c", sql])
    if rc != 0:
        out["error"] = stderr or f"exit {rc}"
        return out

    clients, on_fabric, encrypted, local = [], 0, 0, 0
    for line in stdout.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        addr, user, ssl, count = parts[0], parts[1], parts[2] == "t", int(parts[3])
        if addr == "local":
            # A unix socket never crosses the docker fabric. Counting it as
            # cleartext would inflate the finding with the reader's own session.
            local += count
            continue
        on_fabric += count
        if ssl:
            encrypted += count
        clients.append({"addr": addr, "user": user, "ssl": ssl, "sessions": count})

    clients.sort(key=lambda c: (c["ssl"], -c["sessions"]))
    out.update(
        clients=clients,
        sessions_on_fabric=on_fabric,
        sessions_encrypted=encrypted,
        sessions_unix_socket=local,
        encrypted_ratio=(encrypted / on_fabric) if on_fabric else None,
        basis="live backends, unix socket excluded",
        verdict="GREEN" if on_fabric and encrypted == on_fabric else
                "AMBER" if encrypted else "RED",
    )
    return out


def redis() -> dict:
    """Listener-derived. With `tls-port 0` there is no TLS listener at all, so
    the session count is not an estimate — it is zero by construction.

    Also reports whether the AUTH secret sits on the container's command line
    (REM-217 remediation 1). The value is NEVER read out of the array; only
    whether the flag is present."""
    out = {"datastore": "redis", "container": REDIS, "verdict": "UNKNOWN"}
    docker = _docker()
    if not docker:
        out["error"] = "docker not on PATH"
        return out
    try:
        p = subprocess.run(
            [docker, "inspect", REDIS, "--format", "{{json .Config.Cmd}}"],
            capture_output=True, text=True, timeout=TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as exc:      # pragma: no cover
        out["error"] = str(exc)
        return out
    if p.returncode != 0:
        out["error"] = p.stderr.strip() or f"exit {p.returncode}"
        return out
    try:
        cmd = json.loads(p.stdout or "null") or []
    except json.JSONDecodeError:
        out["error"] = "container command is not JSON"
        return out

    # Flag NAMES only. The argv holds the shared redis secret and this reader
    # must not be the thing that copies it somewhere new.
    flags = {tok.split("=", 1)[0].lstrip("-").split(" ", 1)[0]
             for tok in cmd if isinstance(tok, str) and tok.startswith("--")}
    tls_listener = "tls-port" in flags
    out.update(
        tls_listener=tls_listener,
        secret_on_argv="requirepass" in flags,
        basis="listener configuration; a server with no TLS port has no encrypted sessions",
        verdict="UNKNOWN" if tls_listener else "RED",
    )
    if tls_listener:
        out["note"] = ("a TLS port is configured; the per-session split needs an "
                       "authenticated CONFIG read this reader deliberately does not do")
    else:
        out.update(sessions_encrypted=0, encrypted_ratio=0.0)
    return out


def collect() -> dict:
    return {"datastores": [mariadb(), postgresql(), redis()]}


def _pct(ratio: float | None) -> str:
    if ratio is None:
        return "n/a"
    if ratio == 0:
        return "0%"
    if ratio < 0.001:
        return f"{ratio * 100:.4f}%"
    return f"{ratio * 100:.1f}%"


def render(report: dict) -> list[str]:
    lines = ["datastore transport — what is encrypted, not what is enabled", ""]
    for d in report["datastores"]:
        head = f"  {d['datastore']:<11} {d['verdict']}"
        if d.get("error"):
            lines.append(f"{head}  — could not read: {d['error']}")
            lines.append("")
            continue
        lines.append(head)
        if d["datastore"] == "mariadb":
            up = d.get("uptime_seconds") or 0
            lines.append(f"    {d['ssl_accepts']} TLS handshakes of {d['connections']} "
                         f"connections = {_pct(d['encrypted_ratio'])}")
            lines.append(f"    cumulative over {up // 86400}d {(up % 86400) // 3600}h of "
                         f"uptime — a fix moves the TREND, not this number")
            lines.append("    require_secure_transport=ON — no plaintext session can exist"
                         if d.get("require_secure_transport") else
                         "    require_secure_transport=OFF — plaintext is accepted; only "
                         "this switch can certify the end state")
        elif d["datastore"] == "postgresql":
            lines.append(f"    {d['sessions_encrypted']} of {d['sessions_on_fabric']} "
                         f"backends on the fabric = {_pct(d['encrypted_ratio'])}"
                         f"  ({d['sessions_unix_socket']} on the unix socket, not counted)")
            for c in d["clients"]:
                mark = "TLS " if c["ssl"] else "PLAIN"
                lines.append(f"      {mark:<6}{c['addr']:<14}{c['user']:<12}x{c['sessions']}")
            lines.append("    this is ONE SAMPLE of live backends — a client whose pool is "
                         "idle does not appear at all, so absence here is not evidence "
                         "that it connects encrypted")
        elif d["datastore"] == "redis":
            lines.append("    no TLS listener (tls-port unset) — every one of its "
                         "sessions is cleartext by construction"
                         if not d["tls_listener"] else f"    {d.get('note', '')}")
            if d.get("secret_on_argv"):
                lines.append("    AUTH secret is on the container command line — "
                             "readable by anything that can `docker inspect`")
        lines.append("")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="machine-readable")
    args = ap.parse_args()

    report = collect()
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print("\n".join(render(report)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
