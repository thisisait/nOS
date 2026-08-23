"""REM-217 rung 3 — the MariaDB clients, and their different knobs.

WHAT THIS IS FOR. `docs/idea/21-mariadb-tls-ladder.md` scoped rung 3 as
"`MYSQL_ATTR_SSL_CA` per Laravel client (freescout, firefly, bookstack), and the
equivalents for WordPress and Nextcloud". Read in the running images on
2026-08-23, that is true of exactly ONE of the three Laravel apps:

    bookstack  MYSQL_ATTR_SSL_CA      /app/www/app/Config/database.php:84
    freescout  DB_MYSQL_ATTR_SSL_CA   /www/html/config/database.php:56
    firefly    MYSQL_SSL_CA           /var/www/html/config/database.php:43
               + MYSQL_USE_SSL        …:49 gates the WHOLE block

Three forks of one framework, three names, and firefly needs a second variable
before the first one is even consulted. The scoping generalised from whichever
config it happened to open — the same shortcut that put `no-verify` into Outline
and `?sslmode=` into HedgeDoc
(docs/doctrine/foreign-properties.md §5.2).

So this gate exists to stop the names drifting back together. Copying one of
these lines to a sibling produces a variable nobody reads: it renders, it
resolves, it appears in `docker inspect`, and the client keeps connecting in
clear. That is `docs/hidden_fees/28` and it is invisible without a reader.

WHAT IS PINNED.
  1. Each client declares ITS OWN name, and does not declare a sibling's.
  2. Every client that names a CA path also MOUNTS one, at the single path
     `mariadb_client_ca_path` — and read-only.
  3. WordPress mounts NO CA, deliberately: wpdb never calls `mysqli_ssl_set`,
     so a mounted file would be one nothing reads.
  4. The mount and the knob sit behind the SAME gate. Half-gated, the client
     asks for a CA that is not there — and pdo_mysql fails CLOSED (measured:
     "Cannot connect to MySQL using SSL"), so half-gating is an outage, not a
     silent downgrade.
  5. `require_secure_transport` is DECLARED, and declared OFF. Rung 4 is a
     cliff — it would refuse every client that has not yet moved — but
     OMISSION is not OFF: an undeclared value is whatever last touched the
     server, and no converge can put it back (proven live 2026-08-23).

AND THERE ARE SIX, not five. `mysqld-exporter` was found on 2026-08-23 by
sampling `information_schema.processlist` — the ladder enumerated clients from
a survey of the APPLICATIONS, and a metrics exporter is a database client too.
It is a Go binary with no env knob and is tracked separately
(`sec-transport-mysqld-exporter`); this file pins the five that are
env-configurable, and pins that the sixth is NOT silently forgotten.

WHAT IT CANNOT DO. It cannot say whether any client NEGOTIATED TLS. Nothing in
pytest can — MariaDB exposes no per-session cipher to another session, and the
aggregate `--window` ratio cannot reach 1.0 because the server's own
healthcheck connects over the unix socket every ten seconds. The verdict is
`tools/tls-uptake.py`'s per-client SELF-TESTS, where each client is asked about
its own session through its own option. This gate green means only that the
configuration is coherent.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]

#: service -> (compose template, the env var IT reads, where that was read from)
#: `None` for env means the client is not env-configurable at all.
CLIENTS = {
    "bookstack": ("roles/pazny.bookstack/templates/compose.yml.j2",
                  "MYSQL_ATTR_SSL_CA",
                  "/app/www/app/Config/database.php:84"),
    "freescout": ("roles/pazny.freescout/templates/compose.yml.j2",
                  "DB_MYSQL_ATTR_SSL_CA",
                  "/www/html/config/database.php:56"),
    "firefly": ("roles/pazny.firefly/templates/compose.yml.j2",
                "MYSQL_SSL_CA",
                "/var/www/html/config/database.php:43"),
    "wordpress": ("roles/pazny.wordpress/templates/compose.yml.j2",
                  None,
                  "wp-includes/class-wpdb.php:1959 — flags only, no CA possible"),
    "nextcloud": ("roles/pazny.nextcloud/templates/compose.yml.j2",
                  None,
                  "lib/private/DB/ConnectionFactory.php:201 — occ, no env exists"),
}

#: Clients that mount the CA. WordPress is absent BY DESIGN and that absence is
#: asserted, not merely omitted.
MOUNTS_CA = ("bookstack", "freescout", "firefly", "nextcloud")

GATE = "mariadb_ssl_enabled"


def _config() -> dict:
    return yaml.safe_load((REPO / "default.config.yml").read_text(encoding="utf-8")) or {}


def _src(service: str) -> str:
    return (REPO / CLIENTS[service][0]).read_text(encoding="utf-8")


def test_the_ca_path_is_declared_once_at_play_scope():
    cfg = _config()
    assert "mariadb_client_ca_path" in cfg, (
        "mariadb_client_ca_path must be a play-scope name: five templates, a "
        "post-start occ call and tools/tls-uptake.py all have to agree on one "
        "string, and a role default would be invisible to four of them")
    assert cfg["mariadb_client_ca_path"].startswith("/"), "must be a container path"


def test_each_client_declares_its_own_knob_and_not_a_siblings():
    """The whole point. `MYSQL_ATTR_SSL_CA` in freescout is a variable nobody
    reads — it renders, resolves, and changes nothing."""
    others = {s: {v[1] for k, v in CLIENTS.items() if k != s and v[1]}
              for s in CLIENTS}
    for service, (rel, env, where) in CLIENTS.items():
        src = _src(service)
        if env:
            assert re.search(rf"^\s*{re.escape(env)}\s*:", src, re.M), (
                f"{rel} no longer sets {env} — the only name this image reads "
                f"({where})")
        for foreign in others[service] - ({env} if env else set()):
            assert not re.search(rf"^\s*{re.escape(foreign)}\s*:", src, re.M), (
                f"{rel} sets {foreign}, which belongs to a different fork and "
                f"is ignored here. This one reads {env or 'no env at all'} "
                f"({where})")


def test_firefly_sets_the_gate_that_switches_its_ssl_block_on():
    """`MYSQL_SSL_CA` alone is inert in firefly: config/database.php:49 wraps
    every SSL assignment in `if MYSQL_USE_SSL`. Shipping the CA without it
    would be a pin that renders and does nothing — hidden fee 28, again."""
    src = _src("firefly")
    assert 'MYSQL_USE_SSL: "true"' in src, (
        "firefly's SSL block is gated on MYSQL_USE_SSL; without it the CA is "
        "read into a variable and then skipped")
    on = src.index('MYSQL_USE_SSL: "true"')
    assert GATE in src[max(0, on - 400):on], (
        "MYSQL_USE_SSL=true must sit inside the server-TLS branch — on a host "
        "with no server certificate it would refuse to connect at all")


def test_a_client_that_names_a_ca_also_mounts_one():
    """Matched on the VARIABLE, not on its current value. A gate keyed to the
    literal `/nos-certs/...` would go green the day someone hardcoded the path
    in one template and moved the var in the other — which is the join it is
    here to protect."""
    for service in MOUNTS_CA:
        src = _src(service)
        mounts = [ln for ln in src.splitlines()
                  if "mariadb_client_ca_path" in ln and "server.crt" in ln]
        assert mounts, (
            f"{CLIENTS[service][0]} configures MariaDB TLS but mounts no CA at "
            "mariadb_client_ca_path. pdo_mysql fails CLOSED on a CA it cannot "
            "read, so this is an outage rather than a quiet downgrade")
        assert all(ln.rstrip().endswith(":ro") for ln in mounts), (
            f"{service}: the CA mount must be read-only")
        assert all("mariadb_certs_dir" in ln for ln in mounts), (
            f"{service}: the CA must come from the server's own cert directory, "
            "not a copy — a second copy is a second thing to rotate")


def test_wordpress_mounts_no_ca_because_it_could_not_read_one():
    """Not an omission. wpdb hands MYSQL_CLIENT_FLAGS to mysqli_real_connect and
    never calls mysqli_ssl_set, so there is no way to name a CA from PHP. A file
    mounted anyway would be exactly the inert artifact hidden fee 28 is about —
    and it would read, to the next person, as verification that is not there."""
    src = _src("wordpress")
    assert "mariadb_client_ca_path" not in src, (
        "wordpress mounts the MariaDB CA, which nothing in WordPress can read")
    assert "MYSQL_CLIENT_FLAGS" in src and "MYSQLI_CLIENT_SSL" in src, (
        "wordpress lost its only available control; measured 2026-08-23, the "
        "flag alone negotiates TLS_AES_256_GCM_SHA384")
    assert "WITHOUT AUTHENTICATION" in src.upper(), (
        "the ceiling must stay written where the line is: this encrypts but "
        "does not verify, and a later reader must not mistake it for both")


def test_the_mount_and_the_knob_share_one_gate():
    for service, (rel, env, _where) in CLIENTS.items():
        src = _src(service)
        if GATE not in src:
            assert service not in MOUNTS_CA and not env, (
                f"{rel} configures MariaDB TLS unconditionally; on a host whose "
                "server offers no certificate the client cannot connect")
            continue
        # Every TLS line this gate cares about must be inside a block that
        # tests the gate. Cheap structural proxy: the gate appears at least as
        # often as the {% if %} blocks that carry these lines.
        blocks = src.count(f"{{% if {GATE}")
        assert blocks >= 1, (
            f"{rel} mentions {GATE} but not as a render gate — a variable read "
            "into a comment protects nothing")


def test_the_sixth_client_is_not_quietly_dropped():
    """`mysqld-exporter` is plaintext today and that is a KNOWN open row, not a
    gap. What must not happen is it falling out of the reader's client table —
    at which point the estate goes back to believing there are five, which is
    how it was missed for a day in the first place."""
    reader = (REPO / "tools/tls-uptake.py").read_text(encoding="utf-8")
    assert "mysqld-exporter" in reader, (
        "the sixth MariaDB client is gone from tools/tls-uptake.py. It was "
        "found by sampling the SERVER's connection list, not by reading a "
        "survey of applications — removing it restores the blind spot")
    seed = (REPO / "tools/roadmap-seed.py").read_text(encoding="utf-8")
    assert "sec-transport-mysqld-exporter" in seed, (
        "the exporter's roadmap row is gone; a known-plaintext client with no "
        "row is an unknown-plaintext client")


def test_the_verdict_comes_from_a_self_test_not_from_the_declaration():
    """A declared knob is not an encrypted session — hedgedoc declared an
    sslmode for eight hours while an ORM dropped it (hidden fee 28). The reader
    must carry the per-client self-test, and the probe must read THAT."""
    reader = (REPO / "tools/tls-uptake.py").read_text(encoding="utf-8")
    assert "MARIADB_SELFTESTS" in reader and "def mariadb_selftests" in reader, (
        "the per-client self-tests are gone; nothing else can answer whether a "
        "client with a one-millisecond pool encrypted anything")
    import yaml as _yaml
    probes = _yaml.safe_load(
        (REPO / "state/roadmap-probes.yml").read_text(encoding="utf-8"))
    probe = probes["sec-transport-mariadb-clients"]
    assert "mariadb_selftests" in probe, (
        "the rung-3 probe reads something other than the self-tests")
    assert "window_ratio" not in probe, (
        "the probe is back on the aggregate window ratio, which CANNOT reach "
        "1.0: the server's healthcheck opens a unix-socket connection every "
        "10s and no counter separates it from a plaintext TCP one")


def test_rung_four_has_not_been_climbed_by_accident():
    """`require_secure_transport` would refuse every client that has not moved.
    Measured 2026-08-23: 1 of 9 new connections encrypted. It is the LAST rung
    and this gate is what stops it arriving with rung 3."""
    src = (REPO / "roles/pazny.mariadb/templates/compose.yml.j2").read_text()
    live = [ln.strip() for ln in src.splitlines()
            if "require-secure-transport" in ln.replace("_", "-")
            and not ln.lstrip().startswith("#")]
    # DECLARED OFF is required, not merely permitted (2026-08-23). Omitting the
    # flag left the live value unowned: a `SET GLOBAL require_secure_transport=1`
    # from outside the repository took MariaDB to refusing every plaintext
    # connection, FreeScout logged 264 `[3159]` errors behind a healthcheck that
    # still said healthy, and NO CONVERGE COULD UNDO IT — the playbook cannot
    # reconcile a value it does not declare.
    assert live, (
        "roles/pazny.mariadb no longer declares require-secure-transport at "
        "all. Omission is not OFF: it leaves the live value to whatever last "
        "touched the server, and a converge cannot put it back")
    assert all(l.endswith('=0"') for l in live), (
        "rung 4 is being climbed here. It refuses every client that has not "
        "moved, and the exporter has not:\n  " + "\n  ".join(live))
