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
  * MariaDB's ratio is CUMULATIVE SINCE THE SERVER STARTED. It cannot rise
    quickly even after every client is fixed, so the reader prints uptime
    beside it and says what the number is. `--window N` gives the number that
    CAN move: what fraction of the connections opened in the last N seconds
    were encrypted. A window in which nothing connected reports no rate at
    all — never 0, never 100.
  * The MariaDB per-client table says what each client DECLARES. It is not the
    effect and is labelled so in both renders: MariaDB exposes no per-session
    cipher to another session, and the three Laravel clients read three
    DIFFERENT env var names, so a table like this is the only place that fact
    can live without being re-derived from memory.
  * Redis is reported from its LISTENER, because with `tls-port 0` there is no
    TLS listener and therefore provably zero encrypted sessions — a shape read
    that determines the effect. If a TLS port ever IS configured, the per-
    session split becomes genuinely unknown from outside and says so.

Usage:
    tools/tls-uptake.py              # one block per datastore, plus the clients
    tools/tls-uptake.py --window 30  # what NEW connections did in the last 30s
    tools/tls-uptake.py --json       # for a caller

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
import time

MARIADB = "infra-mariadb-1"
POSTGRES = "infra-postgresql-1"
REDIS = "infra-redis-1"

TIMEOUT = 20


def _docker() -> str | None:
    return shutil.which("docker")


def _exec(container: str, argv: list[str], user: str | None = None) -> tuple[int, str, str]:
    docker = _docker()
    if not docker:
        return 127, "", "docker not on PATH"
    pre = ["-u", user] if user else []
    try:
        p = subprocess.run([docker, "exec", *pre, container, *argv],
                           capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {TIMEOUT}s"
    except OSError as exc:                                  # pragma: no cover
        return 126, "", str(exc)
    return p.returncode, p.stdout, p.stderr.strip()


#: The one SQL the MariaDB read sends. Kept as a module constant so the window
#: sample and the first sample are provably the same statement.
_MARIADB_STATUS_SQL = (
    "select variable_name, variable_value from information_schema.global_status "
    "where variable_name in ('CONNECTIONS','SSL_ACCEPTS','THREADS_CONNECTED','UPTIME'); "
    "select 'REQUIRE_SECURE_TRANSPORT', @@require_secure_transport")


def _mariadb_status() -> tuple[dict, str]:
    """The counters, or an empty dict and the reason."""
    # The root password never leaves the container: `sh -c` expands the env var
    # inside, so it appears on no host argv and in no process list here.
    rc, stdout, stderr = _exec(
        MARIADB,
        ["sh", "-c", f'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -N -B -e "{_MARIADB_STATUS_SQL}"'])
    if rc != 0:
        return {}, stderr or f"exit {rc}"
    vals = {}
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 2:
            try:
                vals[parts[0].strip().upper()] = int(parts[1])
            except ValueError:
                pass
    if "CONNECTIONS" not in vals or "SSL_ACCEPTS" not in vals:
        return {}, "counters missing from global_status"
    return vals, ""


def mariadb(window: int = 0) -> dict:
    """Cumulative TLS uptake, and — with `window` — the present-tense rate.

    THE CUMULATIVE RATIO CANNOT SHOW A FIX. It is counted since server start,
    so a perfect cutover today still reads ~0% against a year of plaintext.
    That is not a nuance to remember: it is the difference between a rung of
    REM-217 being verifiable and not, and this reader had only the unusable
    half until 2026-08-23.

    `--window N` samples the same counters twice, N seconds apart, and reports
    the DELTA — what fraction of the connections opened *just now* were
    encrypted. That is a statement about the present and it moves the moment a
    client is fixed.

    It is still an aggregate. MariaDB keeps no per-session cipher view another
    session can read: `performance_schema` is OFF on this build (`@@version`
    11.8.8), and while `performance_schema.status_by_thread` is compiled in and
    would give exactly that, turning it on costs server memory to answer a
    measurement question. That trade is recorded here rather than taken
    quietly — see `mariadb_clients()` for what is answerable without it.

    A window in which NOTHING connected reports `rate=None`, never 0 and never
    100%: nought-of-nought is the reading this estate has most often mistaken
    for success (`docs/hidden_fees/08`).
    """
    out = {"datastore": "mariadb", "container": MARIADB, "verdict": "UNKNOWN"}
    vals, err = _mariadb_status()
    if err:
        out["error"] = err
        return out

    if window > 0:
        time.sleep(window)
        later, err2 = _mariadb_status()
        if err2:
            out["window_error"] = err2
        else:
            d_conn = later["CONNECTIONS"] - vals["CONNECTIONS"]
            d_tls = later["SSL_ACCEPTS"] - vals["SSL_ACCEPTS"]
            out.update(
                window_seconds=window,
                window_connections=d_conn,
                window_ssl_accepts=d_tls,
                window_ratio=(d_tls / d_conn) if d_conn > 0 else None,
            )

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


#: Where the playbook mounts the MariaDB server certificate inside a client.
#: Must equal `mariadb_client_ca_path` in default.config.yml — pinned by
#: tests/anatomy/test_mariadb_client_tls.py, because a reader looking at a
#: different path than the renderer writes would report every client as
#: unconfigured for ever, and be believed.
CLIENT_CA_PATH = "/nos-certs/mariadb-ca.crt"

#: THE FIVE MARIADB CLIENTS AND THE KNOB EACH ONE ACTUALLY READS.
#:
#: `docs/idea/21-mariadb-tls-ladder.md` scoped rung 3 as "MYSQL_ATTR_SSL_CA per
#: Laravel client (freescout, firefly, bookstack)". That is true of exactly one
#: of the three. Read from each running image on 2026-08-23:
#:
#:   bookstack  MYSQL_ATTR_SSL_CA       /app/www/app/Config/database.php:84
#:   freescout  DB_MYSQL_ATTR_SSL_CA    /www/html/config/database.php:56
#:   firefly    MYSQL_SSL_CA            /var/www/html/config/database.php:43
#:
#: Three forks of the same framework, three names. The scoping generalised from
#: whichever one it happened to read — the same shortcut that put `no-verify`
#: into Outline (doctrine/foreign-properties.md §5.1). Each entry below names
#: the file and line it was read from; re-read them before trusting this table
#: after an image bump.
#:
#: WordPress and Nextcloud are not env-configurable at all and carry their
#: mechanism in `note`.
MARIADB_CLIENTS = (
    {"service": "bookstack", "container": "b2b-bookstack-1",
     "env": "MYSQL_ATTR_SSL_CA",
     "read_from": "/app/www/app/Config/database.php:84 (stock Laravel)"},
    {"service": "freescout", "container": "b2b-freescout-1",
     "env": "DB_MYSQL_ATTR_SSL_CA",
     "read_from": "/www/html/config/database.php:56 (DB_ prefix — NOT stock)"},
    {"service": "firefly", "container": "b2b-firefly-1",
     "env": "MYSQL_SSL_CA",
     "read_from": "/var/www/html/config/database.php:43 (own names entirely)"},
    {"service": "wordpress", "container": "iiab-wordpress-1",
     "env": "WORDPRESS_CONFIG_EXTRA", "expect": "MYSQL_CLIENT_FLAGS",
     "read_from": "wp-config.php:127 -> class-wpdb.php:1959",
     "note": "wpdb passes MYSQL_CLIENT_FLAGS to mysqli_real_connect and never "
             "calls mysqli_ssl_set, so WordPress can ENCRYPT without a CA but "
             "cannot verify from PHP alone — measured working 2026-08-23"},
    {"service": "nextcloud", "container": "iiab-nextcloud-1",
     "occ": "dbdriveroptions",
     "read_from": "config/config.php — no env exists; occ config:system:set",
     "note": "the only one of the five that needs a post-start call rather "
             "than a compose change"},
)


def mariadb_clients() -> list[dict]:
    """What each MariaDB client DECLARES, and whether the CA it would need is
    readable where it runs.

    THIS IS NOT THE EFFECT AND MUST NOT BE READ AS IT. MariaDB exposes no
    per-session cipher to another session, so nothing here proves a client
    negotiated TLS — only that it is configured to and could. The effect half
    is `mariadb(window=N)`, in aggregate, and the two must be read together:
    a client can declare a CA and still connect in clear if its framework
    filters the value out (`array_filter` drops an empty one — that is exactly
    how `MYSQL_ATTR_SSL_CA=""` failed) and the declaration would look fine.

    A container that is not running is `absent`, never `ok`.
    """
    rows: list[dict] = []
    for spec in MARIADB_CLIENTS:
        row = {"service": spec["service"], "container": spec["container"],
               "read_from": spec["read_from"], "state": "UNKNOWN"}
        if spec.get("note"):
            row["note"] = spec["note"]

        rc, _, err = _exec(spec["container"], ["true"])
        if rc != 0:
            row.update(state="ABSENT", detail=err or f"exit {rc}")
            rows.append(row)
            continue

        rc, out, _ = _exec(spec["container"],
                           ["sh", "-c", f'test -r "{CLIENT_CA_PATH}" && echo yes'])
        row["ca_readable"] = out.strip() == "yes"

        if spec.get("env"):
            row["knob"] = spec["env"]
            rc, out, _ = _exec(spec["container"], ["printenv", spec["env"]])
            value = out.strip() if rc == 0 else ""
            expect = spec.get("expect")
            declared = (expect in value) if expect else bool(value)
            row["declared"] = declared
            # The VALUE of a CA path is safe to print (it is a path, not a
            # secret). WORDPRESS_CONFIG_EXTRA can hold anything, so only the
            # presence of the token is reported, never the string.
            row["value"] = value if (declared and not expect) else None
        elif spec.get("occ"):
            row["knob"] = f"occ {spec['occ']}"
            rc, out, _ = _exec(spec["container"],
                               ["php", "occ", "config:system:get", spec["occ"]],
                               user="www-data")
            row["declared"] = rc == 0 and bool(out.strip())
            row["value"] = out.strip() or None

        if row.get("declared") and row.get("ca_readable"):
            row["state"] = "DECLARED"
        elif row.get("declared") and spec["service"] == "wordpress":
            row["state"] = "DECLARED"          # encrypts without a CA, by design
        elif row.get("declared"):
            row["state"] = "BROKEN"            # asks for a CA that is not there
        else:
            row["state"] = "PLAIN"
        rows.append(row)
    return rows


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


def collect(window: int = 0) -> dict:
    return {"datastores": [mariadb(window), postgresql(), redis()],
            "mariadb_clients": mariadb_clients()}


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
            if d.get("window_seconds"):
                n, k = d["window_connections"], d["window_ssl_accepts"]
                lines.append(
                    f"    in the last {d['window_seconds']}s: {k} of {n} NEW connections "
                    f"encrypted = {_pct(d['window_ratio'])}" if n > 0 else
                    f"    in the last {d['window_seconds']}s: NOTHING connected — no rate "
                    "to report, which is not a pass")
            elif d.get("window_error"):
                lines.append(f"    window sample failed: {d['window_error']}")
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

    lines.append("  mariadb clients — what each one DECLARES, not what it negotiated")
    for c in report.get("mariadb_clients", []):
        detail = c.get("detail") or c.get("knob") or ""
        mark = {"DECLARED": "ok  ", "PLAIN": "PLAIN", "BROKEN": "BROKEN",
                "ABSENT": "-   "}.get(c["state"], "?   ")
        lines.append(f"    {mark:<7}{c['service']:<11}{detail}")
        if c["state"] == "BROKEN":
            lines.append(f"             asks for a CA at {CLIENT_CA_PATH}, which is "
                         "NOT readable in this container")
    lines.append("    declared != encrypted: MariaDB exposes no per-session cipher to "
                 "another session, so read this beside --window, never instead of it")
    lines.append("")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="machine-readable")
    ap.add_argument("--window", type=int, default=0, metavar="SECONDS",
                    help="sample MariaDB's counters twice, N seconds apart, and "
                         "report the DELTA — the only present-tense rate it can give")
    args = ap.parse_args()

    report = collect(args.window)
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print("\n".join(render(report)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
