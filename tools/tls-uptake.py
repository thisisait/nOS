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


def _exec(container: str, argv: list[str], user: str | None = None,
          timeout: int | None = None) -> tuple[int, str, str]:
    docker = _docker()
    if not docker:
        return 127, "", "docker not on PATH"
    pre = ["-u", user] if user else []
    try:
        p = subprocess.run([docker, "exec", *pre, container, *argv],
                           capture_output=True, text=True,
                           timeout=timeout or TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout or TIMEOUT}s"
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
#:              (set as ENV_DB_MYSQL_ATTR_SSL_CA — the image's .env passthrough;
#:               the bare name resolves through env() and is still absent from
#:               the cached config, which is where the app actually reads it)
#:   firefly    MYSQL_SSL_CA            /var/www/html/config/database.php:43
#:
#: Three forks of the same framework, three names. The scoping generalised from
#: whichever one it happened to read — the same shortcut that put `no-verify`
#: into Outline (docs/doctrine/foreign-properties.md §5.1). Each entry below names
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
     "env": "ENV_DB_MYSQL_ATTR_SSL_CA",
     "read_from": "/www/html/config/database.php:56, reached via the image's "
                  "ENV_* .env passthrough — the bare name resolves and never "
                  "enters the CACHED config"},
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
    # THE SIXTH CLIENT, and the reason this table is not called "the five".
    # Found 2026-08-23 by sampling `information_schema.processlist`, NOT by
    # reading the ladder — which enumerated five, from a survey of the apps.
    # A metrics exporter is a database client too, and it carries a credential
    # across the fabric roughly four times a minute.
    #
    # It is a Go binary, so there is no self-test to run; its state is read
    # from its ARGV, which determines it: mysqld_exporter 0.19 takes TLS only
    # from `--config.my-cnf` (ssl-ca / ssl-mode) or
    # `--tls.insecure-skip-verify`, verified against the binary's own --help.
    # Neither present = provably plaintext, the same shape as redis's missing
    # TLS listener.
    {"service": "mysqld-exporter", "container": "observability-mysqld-exporter-1",
     "argv_tls": ("--config.my-cnf", "--tls.insecure-skip-verify"),
     "read_from": "prom/mysqld-exporter:v0.19.0 --help",
     "note": "roadmap sec-transport-mysqld-exporter; a my.cnf carrying ssl-ca "
             "also moves the password off the env, but the file must be "
             "readable by the exporter's non-root user — untested, not shipped"},
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

        if spec.get("argv_tls"):
            # Read from the container's command line, like the redis leg.
            docker = _docker()
            row["knob"] = " | ".join(spec["argv_tls"])
            try:
                import subprocess as _sp
                cmd = _sp.run([docker, "inspect", spec["container"],
                               "--format", "{{json .Config.Cmd}}"],
                              capture_output=True, text=True, timeout=TIMEOUT)
                argv = json.loads(cmd.stdout or "[]")
            except Exception:                                   # pragma: no cover
                argv = []
            row["declared"] = any(any(str(a).startswith(f) for a in argv)
                                  for f in spec["argv_tls"])
            row["state"] = "DECLARED" if row["declared"] else "PLAIN"
            rows.append(row)
            continue

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
            rc, out, err = _exec(spec["container"],
                                 ["php", "occ", "config:system:get", spec["occ"]],
                                 user="www-data")
            if rc != 0:
                # A READ THAT FAILED IS NOT A DETERMINATE ANSWER. This branch
                # used to fold a non-zero occ into `declared=False`, i.e. into
                # PLAIN — and occ bootstraps the database, so the one situation
                # where it cannot run is the one where the option is broken.
                # On 2026-08-23 that printed `PLAIN nextcloud` about a service
                # whose CA path was wrong, which reads as "no TLS configured"
                # and was "I could not ask".
                row.update(state="UNKNOWN",
                           detail=(out or err or f"exit {rc}").strip()[:100])
                rows.append(row)
                continue
            row["declared"] = bool(out.strip())
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


#: The per-backend question, sent once per sample. A module constant so the
#: repeated form below is provably the same statement as the single one.
_PG_SSL_SQL = ("select coalesce(host(a.client_addr),'local'), a.usename, s.ssl, count(*) "
               "from pg_stat_ssl s join pg_stat_activity a using(pid) group by 1,2,3")


#: MariaDB clients asked about their OWN session, the way `PG_SELFTESTS` asks
#: HedgeDoc. Same reason, measured the same way: sampling cannot answer here.
#:
#:   * four of the six connect per-request and are gone in under a millisecond
#:     — a 400-sample sweep over a minute caught wordpress, nextcloud and the
#:     exporter ONCE each;
#:   * the aggregate `--window` ratio can never reach 1.0, because MariaDB's
#:     own healthcheck connects over the unix SOCKET every 10 seconds. That is
#:     secure (and `require_secure_transport` exempts sockets) but it is not a
#:     TLS handshake, and no counter separates the two. A threshold on that
#:     ratio is therefore a guess dressed as a measurement.
#:
#: Each snippet reproduces the option THE APP ITSELF READS, from the same env
#: var, inside the app's own container. It is not literally the app's own
#: connection — that is the honest limit — but the configuration, the driver
#: and the network path are the app's.
#:
#: The password never leaves the container: `getenv()` runs in there, so it
#: appears on no host argv and in no output.
#: THE LARAVEL PROBE ASKS THE APPLICATION, NOT THE ENVIRONMENT.
#:
#: The first cut built a PDO from `getenv(<the app's var>)`. It reported
#: `encrypted` for FreeScout while FreeScout was logging 264
#: `[3159] Connections using insecure transport are prohibited` — a FALSE GREEN
#: about a service that could not open a connection at all.
#:
#: The mechanism, measured in the container on 2026-08-23:
#:
#:     env("DB_MYSQL_ATTR_SSL_CA")                  '/nos-certs/mariadb-ca.crt'
#:     config("database.connections.mysql.options") {"1013": true}
#:
#: Laravel CACHES its config (bootstrap/cache/config.php). Once cached, `env()`
#: is never consulted for a config value again — so the variable resolves, and
#: the application never sees it. `env()` and `config()` are two different
#: questions and only the second one is the app's contract.
#:
#: So the probe boots the app's own kernel and hands PDO the app's own resolved
#: options array. That is as close to "the app's own connection" as anything
#: short of instrumenting the app can be, and it is what makes the caveat in
#: MARIADB_SELFTESTS honest rather than decorative.
_LARAVEL_PROBE = (
    'require "%(root)s/vendor/autoload.php";'
    '$app=require "%(root)s/bootstrap/app.php";'
    '$app->make(Illuminate\\Contracts\\Console\\Kernel::class)->bootstrap();'
    '$c=config("database.connections.mysql");'
    'try{$dsn="mysql:host=".$c["host"].";port=".($c["port"]?:3306).";dbname=".$c["database"];'
    '$p=new PDO($dsn,$c["username"],$c["password"],$c["options"]??[]);'
    '$r=$p->query("show status like \'Ssl_cipher\'")->fetch(PDO::FETCH_NUM);'
    'echo $r[1]===""?"plaintext":"encrypted";}'
    'catch(Throwable $e){echo "error:".substr($e->getMessage(),0,70);}'
)

#: Where the app's own PDO options cannot be reached — no Laravel kernel — the
#: probe reproduces the option the app reads. Weaker, and labelled so.
_PDO_PROBE = (
    '$h=getenv("%(host)s");$d=getenv("%(db)s");$u=getenv("%(user)s");$p=getenv("%(pass)s");'
    '$ca=%(ca)s;$opt=[];if($ca)$opt[PDO::MYSQL_ATTR_SSL_CA]=$ca;'
    'try{$c=new PDO("mysql:host=$h;port=3306;dbname=$d",$u,$p,$opt);'
    '$r=$c->query("show status like \'Ssl_cipher\'")->fetch(PDO::FETCH_NUM);'
    'echo $r[1]===""?"plaintext":"encrypted";}'
    'catch(Throwable $e){echo "error:".substr($e->getMessage(),0,70);}'
)

MARIADB_SELFTESTS = (
    # All three are Laravel, and all three are asked through their OWN kernel:
    # the env-var differences that matter for CONFIGURING them (three names,
    # plus firefly's MYSQL_USE_SSL gate) stop mattering once the question is
    # "what did you resolve", which is the only question with a true answer.
    {"service": "bookstack", "container": "b2b-bookstack-1",
     "php": _LARAVEL_PROBE % {"root": "/app/www"}},
    {"service": "freescout", "container": "b2b-freescout-1",
     "php": _LARAVEL_PROBE % {"root": "/www/html"}},
    {"service": "firefly", "container": "b2b-firefly-1",
     "php": _LARAVEL_PROBE % {"root": "/var/www/html"}},
    # WordPress has no CA — wpdb never calls mysqli_ssl_set. The flag alone is
    # the whole control, so the probe uses the flag alone.
    {"service": "wordpress", "container": "iiab-wordpress-1",
     "php": '$m=mysqli_init();$ok=@mysqli_real_connect($m,getenv("WORDPRESS_DB_HOST"),'
            'getenv("WORDPRESS_DB_USER"),getenv("WORDPRESS_DB_PASSWORD"),'
            'getenv("WORDPRESS_DB_NAME"),3306,null,MYSQLI_CLIENT_SSL);'
            'if(!$ok){echo "error:".substr(mysqli_connect_error(),0,70);}'
            'else{$r=$m->query("show status like \'Ssl_cipher\'")->fetch_row();'
            'echo $r[1]===""?"plaintext":"encrypted";}'},
    # Nextcloud's option lives in config.php, not the environment, so the probe
    # reads it back through occ — the same value the app loads.
    {"service": "nextcloud", "container": "iiab-nextcloud-1",
     "php": '$ca=trim(shell_exec("php /var/www/html/occ config:system:get dbdriveroptions 1009 2>/dev/null"));'
            + _PDO_PROBE % {"host": "MYSQL_HOST", "db": "MYSQL_DATABASE", "user": "MYSQL_USER",
                            "pass": "MYSQL_PASSWORD", "ca": '$ca'},
     "user": "www-data"},
)


def mariadb_selftests() -> list[dict]:
    """Ask each MariaDB client about its own session. UNKNOWN on any failure —
    a client that cannot be asked is not a client that is encrypted."""
    rows = []
    for spec in MARIADB_SELFTESTS:
        row = {"service": spec["service"], "container": spec["container"], "state": "UNKNOWN"}
        rc, stdout, stderr = _exec(spec["container"], ["php", "-r", spec["php"]],
                                   user=spec.get("user"), timeout=60)
        answer = (stdout or "").strip().splitlines()[-1:] or [""]
        answer = answer[0].strip()
        if answer in ("encrypted", "plaintext"):
            row["state"] = answer.upper()
        else:
            row["detail"] = answer or (stderr or f"exit {rc}")[:120]
        rows.append(row)
    return rows


def postgresql(window: int = 0) -> dict:
    """Per-backend, live. `pg_stat_ssl` is the honest source: it reports what
    each session NEGOTIATED, not what the server offers.

    ONE SAMPLE IS NOT ENOUGH, and 2026-08-23 is when that stopped being a
    caveat and became a defect. HedgeDoc's Sequelize pool closes idle
    connections, so its backend exists only for the instant of a query: a
    single sample sees it perhaps a quarter of the time. `sec-transport-pg`
    read 38-of-38 = done on a sample that missed it, and the row went
    `confirmed` on an accident (docs/hidden_fees/29).

    With `window`, this samples repeatedly over N seconds THROUGH ONE psql
    connection (`pg_sleep` between statements — a hundred `docker exec`s is
    minutes of wall clock for the same answer) and aggregates per client:

        observations  how many samples saw this user at all
        ssl           True only if EVERY observation was encrypted

    So a client that is transient is still seen, and a client that is
    sometimes plaintext cannot hide behind a lucky sample. A user never
    observed is simply absent — which is why the probe asks for a NAMED set
    and reports `unsampled:<who>` rather than reading absence as health.
    """
    out = {"datastore": "postgresql", "container": POSTGRES, "verdict": "UNKNOWN"}
    if window > 0:
        # ~4 samples a second is enough to catch a query-lifetime backend and
        # costs one connection.
        rounds = max(1, int(window * 4))
        script = f"; select pg_sleep(0.25); ".join([_PG_SSL_SQL] * rounds)
        argv = ["psql", "-U", "postgres", "-tAF|", "-c", script]
    else:
        rounds = 1
        argv = ["psql", "-U", "postgres", "-tAF|", "-c", _PG_SSL_SQL]

    rc, stdout, stderr = _exec(POSTGRES, argv, timeout=max(TIMEOUT, window + 30))
    if rc != 0:
        out["error"] = stderr or f"exit {rc}"
        return out

    # user+addr -> [observations, samples_seen_encrypted, peak sessions]
    seen: dict[tuple[str, str], list[int]] = {}
    local = 0
    for line in stdout.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        addr, user, ssl, count = parts[0], parts[1], parts[2] == "t", int(parts[3])
        if addr == "local":
            # A unix socket never crosses the docker fabric. Counting it as
            # cleartext would inflate the finding with the reader's own session.
            local = max(local, count)
            continue
        row = seen.setdefault((addr, user), [0, 0, 0])
        row[0] += 1
        if ssl:
            row[1] += 1
        row[2] = max(row[2], count)

    clients = [{"addr": addr, "user": user,
                "ssl": obs == enc,           # only if EVERY observation was TLS
                "observations": obs,
                "plaintext_observations": obs - enc,
                "sessions": peak}
               for (addr, user), (obs, enc, peak) in seen.items()]
    clients.sort(key=lambda c: (c["ssl"], -c["sessions"]))

    on_fabric = sum(c["sessions"] for c in clients)
    encrypted = sum(c["sessions"] for c in clients if c["ssl"])
    out.update(
        clients=clients,
        samples=rounds,
        sessions_on_fabric=on_fabric,
        sessions_encrypted=encrypted,
        sessions_unix_socket=local,
        encrypted_ratio=(encrypted / on_fabric) if on_fabric else None,
        basis=("live backends, unix socket excluded"
               + (f"; {rounds} samples over ~{window}s so a short-lived pool is "
                  "seen at all" if rounds > 1 else "; ONE sample — a client "
                  "whose pool is idle does not appear")),
        verdict="GREEN" if on_fabric and encrypted == on_fabric else
                "AMBER" if encrypted else "RED",
    )
    return out


#: PostgreSQL clients whose pool is too SHORT-LIVED for sampling to see, with
#: the one-liner that makes each one answer about ITSELF.
#:
#: WHY THIS EXISTS. HedgeDoc's Sequelize pool opens a connection, runs a
#: sub-millisecond `count(*)`, and drops it. Measured 2026-08-23: 319 samples
#: over 100 seconds, across at least three healthcheck cycles that each
#: provably query the database — hedgedoc appeared in ZERO of them. No sampling
#: rate fixes that; the question has to change.
#:
#: So the client is asked to report on its own backend, through its own config
#: and its own driver:
#:
#:     select ssl from pg_stat_ssl where pid = pg_backend_pid()
#:
#: That is deterministic and it is the app's real contract — config.json plus
#: CMD_DB_URL, loaded by HedgeDoc's own module. It is still a READ (one SELECT;
#: loading Sequelize models defines them, it does not sync or migrate).
#:
#: WHAT IT DOES NOT PROVE: that some *other* connection the app makes is
#: encrypted. There is one database config, so on this estate that is the whole
#: surface — but it is an inference, not a measurement, and it is written here
#: rather than assumed.
PG_SELFTESTS = (
    {"service": "hedgedoc", "container": "b2b-hedgedoc-1",
     "why": "Sequelize pool drops the connection between queries — 0 of 319 samples",
     "argv": ["node", "-e",
              'process.chdir("/hedgedoc");'
              'const m=require("/hedgedoc/lib/models");'
              'm.sequelize.query("select ssl from pg_stat_ssl where pid = pg_backend_pid()",'
              '{type:m.Sequelize.QueryTypes.SELECT})'
              '.then(r=>{console.log(r[0]&&r[0].ssl?"encrypted":"plaintext");process.exit(0);})'
              '.catch(e=>{console.log("error:"+String(e).slice(0,80));process.exit(1);});']},
)


def postgres_selftests() -> list[dict]:
    """Ask each short-pool client about its own session. UNKNOWN on any failure
    — a client that cannot be asked is not a client that is encrypted."""
    rows = []
    for spec in PG_SELFTESTS:
        row = {"service": spec["service"], "container": spec["container"],
               "why": spec["why"], "state": "UNKNOWN"}
        rc, stdout, stderr = _exec(spec["container"], spec["argv"], timeout=60)
        answer = (stdout or "").strip().splitlines()[-1:] or [""]
        answer = answer[0]
        if rc != 0 or answer.startswith("error:"):
            row["detail"] = answer or (stderr or f"exit {rc}")[:120]
        elif answer in ("encrypted", "plaintext"):
            row["state"] = answer.upper()
        else:
            row["detail"] = f"unrecognised answer: {answer[:60]!r}"
        rows.append(row)
    return rows


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
    return {"datastores": [mariadb(window), postgresql(window), redis()],
            "mariadb_clients": mariadb_clients(),
            "mariadb_selftests": mariadb_selftests(),
            "postgres_selftests": postgres_selftests()}


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
                obs = f"  seen in {c['observations']}/{d.get('samples', 1)}" if d.get("samples", 1) > 1 else ""
                bad = f"  ({c['plaintext_observations']} PLAINTEXT)" if c.get("plaintext_observations") else ""
                lines.append(f"      {mark:<6}{c['addr']:<14}{c['user']:<12}x{c['sessions']}{obs}{bad}")
            n = d.get("samples", 1)
            if n > 1:
                lines.append(f"    {n} samples — a pool that opens a connection only to "
                             "run a query IS seen here; `ssl` is true only if EVERY "
                             "observation of that client was encrypted")
                lines.append("    a client absent from all of them is still absent, not "
                             "encrypted — ask for a NAMED set, never for silence")
            else:
                lines.append("    this is ONE SAMPLE of live backends — a client whose pool "
                             "is idle does not appear at all, so absence here is not "
                             "evidence that it connects encrypted")
        elif d["datastore"] == "redis":
            lines.append("    no TLS listener (tls-port unset) — every one of its "
                         "sessions is cleartext by construction"
                         if not d["tls_listener"] else f"    {d.get('note', '')}")
            if d.get("secret_on_argv"):
                lines.append("    AUTH secret is on the container command line — "
                             "readable by anything that can `docker inspect`")
        lines.append("")

    for t in report.get("postgres_selftests", []):
        mark = {"ENCRYPTED": "ok  ", "PLAINTEXT": "PLAIN", "UNKNOWN": "?   "}.get(t["state"], "?   ")
        lines.append(f"  postgres self-test  {mark} {t['service']} — asked its own session "
                     f"({t['why']})")
        if t.get("detail"):
            lines.append(f"      {t['detail']}")
    lines.append("")
    lines.append("  mariadb clients — what each one DECLARES, not what it negotiated")
    for c in report.get("mariadb_clients", []):
        detail = c.get("detail") or c.get("knob") or ""
        mark = {"DECLARED": "ok  ", "PLAIN": "PLAIN", "BROKEN": "BROKEN",
                "ABSENT": "-   "}.get(c["state"], "?   ")
        lines.append(f"    {mark:<7}{c['service']:<16}{detail}")
        if c["state"] == "BROKEN":
            lines.append(f"             asks for a CA at {CLIENT_CA_PATH}, which is "
                         "NOT readable in this container")
    lines.append("    declared != encrypted: MariaDB exposes no per-session cipher to "
                 "another session, so read the self-tests below, not this")
    lines.append("")
    lines.append("  mariadb self-tests — each client's OWN option, own driver, own container")
    for t in report.get("mariadb_selftests", []):
        mark = {"ENCRYPTED": "ok  ", "PLAINTEXT": "PLAIN", "UNKNOWN": "?   "}.get(t["state"], "?   ")
        lines.append(f"    {mark:<7}{t['service']:<16}{t.get('detail', '')}")
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
