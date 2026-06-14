"""Anatomy gate (REM-003) — Redis requirepass enforced + every client authenticates.

CRITICAL finding REM-003: Redis ran with ZERO authentication. Resolved by adding
``--requirepass`` to the redis-server command (and ``-a`` to the healthcheck), plus
a password segment on every Redis client connection. This gate pins that posture so
a future edit can't silently regress Redis to open-access:

  1. The redis server command carries ``--requirepass {{ redis_password ... }}``.
  2. The redis healthcheck authenticates with ``-a {{ redis_password ... }}``.
  3. ``redis_password`` is defined in default.credentials.yml.
  4. Every template that opens a Redis client connection includes the password —
     either an embedded ``redis://:<pw>@`` URI or a REDIS*PASSWORD/PWD/SERVERS env
     carrying the password token. A bare ``redis://host`` (no credential) is a leak.

CI-safe: pure source/text scan; no Docker, no live system.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
REDIS = REPO / "roles/pazny.redis/templates/compose.yml.j2"
CREDS = REPO / "default.credentials.yml"

# The canonical password token (server-side default + every client).
PW_TOKEN = "redis_password"

# Every template known to open a Redis *client* connection. If a service starts
# talking to redis it must be added here AND authenticate — that is the point.
CLIENT_TEMPLATES = [
    "roles/pazny.authentik/templates/compose.yml.j2",
    "roles/pazny.erpnext/templates/compose.yml.j2",
    "roles/pazny.outline/templates/compose.yml.j2",
    "roles/pazny.infisical/templates/compose.yml.j2",
    "roles/pazny.superset/templates/compose.yml.j2",
    "roles/pazny.firefly/templates/compose.yml.j2",
    "roles/pazny.onlyoffice/templates/compose.yml.j2",
    "roles/pazny.bookstack/templates/compose.yml.j2",
    "roles/pazny.bookstack/templates/env.j2",
    "roles/pazny.grafana/templates/compose.yml.j2",  # redis-exporter
]


def test_redis_server_enforces_requirepass():
    text = REDIS.read_text()
    cmd = next((ln for ln in text.splitlines() if "redis-server" in ln), "")
    assert cmd, "no redis-server command line found"
    assert "--requirepass" in cmd, f"redis-server must enforce --requirepass: {cmd!r}"
    assert PW_TOKEN in cmd, f"--requirepass must reference {PW_TOKEN}: {cmd!r}"


def test_redis_healthcheck_authenticates():
    text = REDIS.read_text()
    hc = next((ln for ln in text.splitlines() if "redis-cli" in ln), "")
    assert hc, "no redis-cli healthcheck line found"
    assert '"-a"' in hc or " -a " in hc, f"healthcheck must pass -a auth flag: {hc!r}"
    assert PW_TOKEN in hc, f"healthcheck must reference {PW_TOKEN}: {hc!r}"


def test_redis_password_defined_in_credentials():
    text = CREDS.read_text()
    assert re.search(rf"^{PW_TOKEN}\s*:", text, re.M), (
        f"{PW_TOKEN} must be defined in default.credentials.yml"
    )


# A line that connects to redis with no credential: scheme://host (no ':<pw>@').
_BARE_URI = re.compile(r"redis://(?!:)[^@\s\"']*[\"'\s]")

# Env keys (across services) that carry the redis password: AUTHENTIK_REDIS__PASSWORD,
# REDIS_PASSWORD, REDIS_SERVER_PWD, REDIS_SERVERS (bookstack inline-credential form).
_PW_ENV_KEY = re.compile(r"REDIS_*PASSWORD|REDIS_SERVER_PWD|REDIS_SERVERS")


def test_every_redis_client_authenticates():
    """No client template may contain a credential-less redis:// URI, and every
    client template that references redis must carry the password token."""
    for rel in CLIENT_TEMPLATES:
        path = REPO / rel
        text = path.read_text()
        # Lines that look like a redis client connection (URI or a password-bearing env key).
        connection_lines = [
            ln
            for ln in text.splitlines()
            if ("redis://" in ln or _PW_ENV_KEY.search(ln))
        ]
        assert connection_lines, f"{rel}: expected a redis client connection, found none"

        # The whole client template must carry the password token at least once...
        assert PW_TOKEN in text, (
            f"{rel}: redis client references no {PW_TOKEN} token (open access)"
        )
        # ...and every embedded redis:// URI must carry an inline ':<pw>@' credential
        # (the redis-exporter REDIS_ADDR form authenticates via a sibling REDIS_PASSWORD
        # env, so it is exempted from the inline-credential requirement here).
        for ln in connection_lines:
            if "redis://" in ln and "REDIS_ADDR" not in ln:
                assert PW_TOKEN in ln, (
                    f"{rel}: redis:// URI lacks the {PW_TOKEN} credential (open access): "
                    f"{ln.strip()!r}"
                )

        # Guard against a bare credential-less URI slipping in (excluding redis-exporter's
        # REDIS_ADDR which authenticates via a separate REDIS_PASSWORD env).
        for ln in text.splitlines():
            if _BARE_URI.search(ln) and "REDIS_ADDR" not in ln:
                raise AssertionError(
                    f"{rel}: credential-less redis:// URI (REM-003 regression): {ln.strip()!r}"
                )
