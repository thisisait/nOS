"""Anatomy gate (SEC-02) — firefly off shared_net onto gated_b2b_net (+ DB reach).

Firefly's remote_user_guard trusts the REMOTE_USER/X-authentik header with ZERO
validation, so it must not sit on the flat shared_net where a peer could forge it.
Move it to b2b_net + a Traefik-only gated_b2b_net; MariaDB + Redis also join
gated_b2b_net so firefly reaches its DB without shared_net. Pins the wiring +
the base-template external declarations (or compose-up fails "network not defined").

CI-safe: source/YAML scan; no Docker.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
FIREFLY = REPO / "roles/pazny.firefly/templates/compose.yml.j2"
MARIADB = REPO / "roles/pazny.mariadb/templates/compose.yml.j2"
REDIS = REPO / "roles/pazny.redis/templates/compose.yml.j2"
B2B_BASE = REPO / "templates/stacks/b2b/docker-compose.yml.j2"
INFRA_BASE = REPO / "templates/stacks/infra/docker-compose.yml.j2"


def _service_networks(template_text: str) -> list[str]:
    m = re.search(r"\n    networks:\n((?:\s*#.*\n|\s*-\s*\S+\n)+)", template_text)
    assert m, "no service networks: block found"
    return re.findall(r"^\s*-\s+(\S+)", m.group(1), re.M)


def test_firefly_off_shared_on_gated():
    items = _service_networks(FIREFLY.read_text())
    assert "gated_b2b_net" in items and "b2b_net" in items, (
        f"firefly must join b2b_net + gated_b2b_net, got {items}"
    )
    assert not any("shared" in i for i in items), (
        f"firefly must be OFF shared_net (SEC-02), got {items}"
    )


def test_firefly_trusted_proxies_not_wildcard():
    assert 'TRUSTED_PROXIES: "**"' not in FIREFLY.read_text(), (
        "TRUSTED_PROXIES must not be the trust-all wildcard"
    )


def test_mariadb_redis_join_gated_b2b_net():
    assert "gated_b2b_net" in MARIADB.read_text(), "mariadb must join gated_b2b_net (firefly DB reach)"
    assert "gated_b2b_net" in REDIS.read_text(), "redis must join gated_b2b_net (firefly cache reach)"


def test_base_templates_declare_gated_nets_external():
    b2b = B2B_BASE.read_text()
    infra = INFRA_BASE.read_text()
    assert "gated_b2b_net:" in b2b and "external: true" in b2b, "b2b base must declare gated_b2b_net external"
    assert "gated_net:" in infra and "gated_b2b_net:" in infra, (
        "infra base must declare both gated nets external (Traefik + mariadb/redis live here)"
    )
