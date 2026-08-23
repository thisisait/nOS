"""MariaDB gets a certificate on disk, and does not get a cliff with it.

WHY A CERT ON DISK IS THE WHOLE POINT. MariaDB 11 reports `have_ssl=YES` with
`ssl_cert` EMPTY: it generates ephemeral in-memory material when none is
configured. So a client that asks gets `TLS_AES_256_GCM_SHA384`, and there is
still no certificate anywhere a client could point at. REM-217 measured the
consequence — 108 TLS handshakes out of 635,888 connections, the MariaDB root
password crossing three docker networks in clear.

The reason that matters is not cryptographic, it is `array_filter`. Laravel —
freescout, firefly and bookstack, three of the five clients — exposes exactly
one knob, `MYSQL_ATTR_SSL_CA`, and drops it when empty. `MYSQL_ATTR_SSL_CA=""`
is proven to work at the PDO level and is unreachable through the framework.
A real file path is the prerequisite every later rung waits on.

WHAT THIS GATE PINS.

  1. The cert is generated idempotently, with `mariadb` in the SAN — the name
     every client on the fabric actually connects to, so this file works as a
     CA that verifies the host name too.
  2. The heal step survives. It is not defensive boilerplate: it was
     root-caused live on 2026-07-19 against PostgreSQL. If compose mounts the
     paths before openssl writes them, Docker invents them as DIRECTORIES, the
     `creates:` guard then reports "it exists" forever, and the server refuses
     to start on a cert file with no start line.
  3. **`require_secure_transport` is DECLARED, and declared OFF.** Turning it
     on is rung 4 and it is a cliff — today it would refuse 99.98% of
     connections. This leg used to forbid the flag ENTIRELY, and that was wrong
     in a way only the live estate could show: omission leaves the value
     unowned. On 2026-08-23 a `SET GLOBAL require_secure_transport=1` from
     outside this repository took FreeScout down behind a healthcheck that
     still reported healthy, and no converge could undo it, because the
     playbook cannot reconcile a value it never declared. When rung 4 is
     genuinely climbed, change the `0` to a `1` here — deliberately, with
     `tools/tls-uptake.py` showing every client already encrypted.
  4. The toggle is at PLAY scope. Its PostgreSQL twin spent nine weeks as a
     role default that no client role could see (`docs/hidden_fees/23`), and
     this variable will have exactly the same readers.

WHAT IT CANNOT SEE. Whether the container starts, whether MariaDB accepts the
key's ownership through the bind mount, or whether a single client ever asks
for TLS. Only a converge and `tools/tls-uptake.py` answer those.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles/pazny.mariadb"
TASKS = ROLE / "tasks/main.yml"
COMPOSE = ROLE / "templates/compose.yml.j2"


def test_the_toggle_is_at_play_scope():
    cfg = yaml.safe_load((REPO / "default.config.yml").read_text(encoding="utf-8")) or {}
    assert "mariadb_ssl_enabled" in cfg, (
        "mariadb_ssl_enabled must be declared in default.config.yml, not only "
        "in the role — the client roles that will read it are other roles, and "
        "postgresql already paid nine weeks of plaintext for that mistake")
    assert "mariadb_certs_dir" in cfg


def test_the_cert_is_generated_idempotently_with_the_fabric_name():
    src = TASKS.read_text(encoding="utf-8")
    body = src[src.index("Generate self-signed server cert"):]
    nxt = body.index("- name:", 10) if "- name:" in body[10:] else len(body)
    body = body[:nxt]
    assert "creates:" in body, (
        "without a creates: guard every converge rotates the cert and churns "
        "the container that every b2b database sits behind")
    assert "DNS:mariadb" in body, (
        "the SAN must carry `mariadb` — that is the name clients dial on the "
        "docker fabric, and without it a client using this file as its CA "
        "gets a host-name mismatch instead of a working connection")
    assert "chmod 600 server.key" in body


def test_the_heal_step_survives():
    src = TASKS.read_text(encoding="utf-8")
    assert "purged-invalid-certs" in src, (
        "the dir-mount / empty-cert heal is gone. It exists because a "
        "converge-after-crash leaves server.crt as a DIRECTORY, and the "
        "creates: guard then skips regeneration forever — root-caused live on "
        "postgresql, 2026-07-19")
    assert "rm -f" in src and "mariadb_container_name" in src, (
        "healing the paths without dropping the container leaves a bind mount "
        "whose TYPE cannot change on restart (`not a directory`)")


def _render(ssl: bool) -> dict:
    """Render the fragment and parse it.

    Reading the template TEXT is what let the first cut of this file fail on
    its own explanatory comment — the word `require_secure_transport` appears
    there precisely to say it is NOT wired. It is also the mistake
    `docs/hidden_fees/23` is about, one layer up: the template said `require`
    for nine weeks and the render said `prefer`. Judge the artifact.
    """
    import jinja2

    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    out = env.from_string(COMPOSE.read_text(encoding="utf-8")).render(
        mariadb_version="11.8.8", mariadb_port=3306, mariadb_root_password="x",
        mariadb_ssl_enabled=ssl, mariadb_certs_dir="/certs-host",
        mariadb_container_name="infra-mariadb-1", mariadb_data_dir="/d",
        stacks_dir="/s", stacks_shared_network="shared_net",
        mariadb_mem_limit="1g", docker_mem_limit_standard="1g",
        docker_cpus_standard="1.0",
        ansible_facts={"env": {"HOME": "/home/op"}})
    return yaml.safe_load(out)["services"]["mariadb"]


def test_the_cliff_is_declared_and_not_climbed():
    """Rung 2 must stay invisible to every plaintext client — and rung 4 must be
    DECLARED OFF rather than omitted.

    This gate used to forbid the flag entirely. That was wrong in a way only a
    live estate could show: omission leaves the value UNOWNED. On 2026-08-23
    something outside this repository ran `SET GLOBAL
    require_secure_transport=1`, MariaDB began refusing every plaintext
    connection, FreeScout logged 264 `[3159] Connections using insecure
    transport are prohibited` behind a healthcheck that still said healthy, and
    no converge could put it back — the playbook cannot reconcile a value it
    never declared.

    It also contradicted its sibling in test_mariadb_client_tls.py once that
    one started requiring the declaration. Two gates inspecting the same
    property for opposite things is worse than either alone: whichever runs
    first decides, and the other reads as noise.
    """
    svc = _render(ssl=True)
    args = [str(a) for a in svc["command"]]
    assert "--ssl-cert=/certs/server.crt" in args
    assert "--ssl-key=/certs/server.key" in args

    flags = [a for a in args if "require-secure-transport" in a.lower().replace("_", "-")]
    assert flags == ["--require-secure-transport=0"], (
        "rung 4 must be rendered, and rendered OFF. Measured 2026-08-23: ON "
        "refuses 99.98% of connections (108 TLS handshakes out of 635,888) and "
        f"the exporter still has no TLS at all. Got: {flags}")


def test_the_mount_and_the_flags_share_one_gate():
    """Half-gated, the container either mounts certs it never reads or reads
    certs that were never mounted; the second one refuses to start."""
    on, off = _render(ssl=True), _render(ssl=False)

    on_vols = [v for v in on["volumes"] if "/certs/" in v]
    assert len(on_vols) == 2, on["volumes"]
    assert all(v.endswith(":ro") for v in on_vols), on_vols

    assert not [v for v in off["volumes"] if "/certs/" in v], (
        "certs mounted with TLS off — the paths do not exist on that host and "
        "Docker would invent them as directories")
    assert not [a for a in off["command"] if "ssl" in str(a).lower()], (
        "the server is told to read certificate files that are not mounted")
