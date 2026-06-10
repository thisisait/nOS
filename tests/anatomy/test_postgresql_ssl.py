"""S3 gates (2026-06-10) — PostgreSQL in-transit TLS (REM-009).

Server-side ssl=on with a role-generated SELF-SIGNED cert: sslmode=require
never verifies the CA, so self-signed serves the in-transit goal without
entangling mkcert/LE (works on local AND public TLDs). libpq clients
(sslmode=prefer default) upgrade automatically; explicit prefer is set
where templates carried sslmode=disable. Live-verified TLSv1.3 2026-06-10.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]

PG = REPO / "roles/pazny.postgresql"
COMPOSE = PG / "templates/compose.yml.j2"
TASKS = PG / "tasks/main.yml"
DEFAULTS = PG / "defaults/main.yml"


def test_ssl_toggle_darwin_gated():
    src = DEFAULTS.read_text()
    assert "postgresql_ssl_enabled" in src
    # Linux: PG refuses a host-user-owned key (needs postgres-uid or root);
    # the Darwin gate keeps the ubuntu CI wet-test green until the
    # root-chown leg lands. Flipping this to a bare `true` without that leg
    # breaks integration-linux.
    assert 'ansible_os_family == \'Darwin\'' in src.replace('"', "'")


def test_cert_generation_is_idempotent_and_gated():
    src = TASKS.read_text()
    body = src[src.index("Generate self-signed server cert"):]
    body = body[:body.index("- name:", 10) if "- name:" in body[10:] else len(body)]
    assert "creates:" in body, (
        "cert generation lost its creates: guard — every run would rotate "
        "the cert and churn the container"
    )
    assert "postgresql_ssl_enabled" in body
    assert "chmod 600 server.key" in body
    assert "subjectAltName=DNS:postgresql,IP:127.0.0.1" in body


def test_compose_wires_ssl_when_enabled():
    src = COMPOSE.read_text()
    assert "ssl=on" in src and "ssl_cert_file=/certs/server.crt" in src
    # Both the mounts and the command flags must sit behind the same gate —
    # half-gated (mount without ssl=on, or vice versa) breaks container start.
    assert src.count("postgresql_ssl_enabled | default(false)") >= 2
    assert "/certs/server.key:ro" in src


def test_clients_do_not_regress_to_disable():
    """sslmode=disable was templated into miniflux + postgres_exporter; both
    flipped to prefer (TLS when offered, plaintext fallback — safe with SSL
    off). A new explicit disable is a silent in-transit downgrade."""
    for rel in (
        "roles/pazny.miniflux/templates/compose.yml.j2",
        "roles/pazny.grafana/templates/compose.yml.j2",
    ):
        src = (REPO / rel).read_text()
        assert "sslmode=disable" not in src, f"{rel} regressed to sslmode=disable"
        assert "sslmode=prefer" in src

    authentik = (REPO / "roles/pazny.authentik/templates/compose.yml.j2").read_text()
    assert authentik.count('AUTHENTIK_POSTGRESQL__SSLMODE: "prefer"') == 2, (
        "authentik server AND worker env blocks must both carry "
        "SSLMODE=prefer (its own default left connections plaintext even "
        "with the server offering TLS — observed live in pg_stat_ssl)"
    )
