"""S3 gates (2026-06-10) — PostgreSQL in-transit TLS (REM-009), rewritten
2026-08-23 after REM-217 measured what they had actually been protecting.

Server-side ssl=on with a role-generated SELF-SIGNED cert, so a client must not
verify the CA — that part held and still holds.

THE CLIENT HALF DID NOT, AND THE OLD GATE COULD NOT SEE IT. It asserted exact
strings: `sslmode={{ 'require' if (postgresql_ssl_enabled | default(false))
else 'prefer' }}`. That string was present in the templates the whole time and
never once rendered `require`, because `postgresql_ssl_enabled` was a
`pazny.postgresql` ROLE default and the clients that read it are other roles.
Two months later the vault, Outline, HedgeDoc and 22 Authentik backends were
still cleartext, and this file was green every day.

So the gate now pins the PROPERTY instead of the spelling:

  1. Every PostgreSQL client declares an sslmode explicitly — no silent
     library default, in either direction.
  2. On the server-TLS branch the value must ENCRYPT. `prefer` no longer
     qualifies: it PERMITS plaintext, and measured on this estate the
     permission was taken by every client whose driver does not upgrade
     opportunistically. `disable` never qualified.
  3. Which encrypting spelling is a fact about the CLIENT LIBRARY, not a
     style choice, and the table below records it with the reason —
     `require` means opposite things in libpq and node-postgres.

And the leg that would have caught the original defect: the variable every one
of these conditionals reads must be resolvable where it is read. That is
`tests/anatomy/test_a_role_default_is_not_read_across_roles.py`.

None of this can say what the estate NEGOTIATES. `tools/tls-uptake.py` does,
and it is the only thing that should be believed on that question.
"""
from __future__ import annotations

import pathlib
import re

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


#: Every PostgreSQL client this estate renders, with the encrypting sslmode its
#: driver family requires and WHY that spelling and not the other one.
#:
#: Doctrine: docs/doctrine/foreign-properties.md §5 — the word means opposite
#: things in the two client families, and that is upstream's, not ours.
#:
#: The split is not cosmetic. In libpq, `require` = encrypt, do NOT verify the
#: certificate — correct against a self-signed server cert. In node-postgres
#: (`pg-connection-string`) the same word leaves `rejectUnauthorized` at Node's
#: default of TRUE, so it would REJECT that cert and the service would fail to
#: start; only `no-verify` disables verification there. One word, two libraries,
#: opposite failure modes.
#:
#: Driver family is established EMPIRICALLY where possible: a client that
#: negotiated TLS while set to `prefer` is libpq-family, because a node-postgres
#: client never upgrades opportunistically.
CLIENTS = (
    ("roles/pazny.authentik/templates/compose.yml.j2", "AUTHENTIK_POSTGRESQL__SSLMODE",
     "require", "psycopg → libpq", 2),
    ("roles/pazny.paperclip/templates/compose.yml.j2", "DATABASE_URL",
     "require", "libpq-family: negotiated TLS under prefer", 1),
    ("roles/pazny.miniflux/templates/compose.yml.j2", "DATABASE_URL",
     "require", "Go lib/pq → libpq semantics; live TLS under prefer", 1),
    ("roles/pazny.grafana/templates/compose.yml.j2", "DATA_SOURCE_NAME",
     "require", "postgres_exporter, Go lib/pq", 1),
    ("roles/pazny.hedgedoc/templates/compose.yml.j2", "CMD_DB_URL",
     "no-verify", "Sequelize → node-postgres; `require` would reject the cert", 1),
    ("roles/pazny.outline/templates/compose.yml.j2", "PGSSLMODE",
     "no-verify", "node-postgres; was `disable`, upstream sample boilerplate", 1),
    ("roles/pazny.infisical/templates/compose.yml.j2", "DB_CONNECTION_URI",
     "no-verify", "knex → node-postgres; had NO sslmode at all, the vault in clear", 1),
)

#: Values that permit a plaintext session. `prefer` is here on evidence, not on
#: principle: under `prefer` the estate measured 22 cleartext Authentik backends
#: against a server with ssl=on.
PERMITS_PLAINTEXT = ("disable", "prefer", "allow")


def _client_lines(rel: str, key: str) -> list[str]:
    src = (REPO / rel).read_text()
    return [ln for ln in src.splitlines() if ln.lstrip().startswith(key + ":")]


def test_every_client_declares_an_sslmode_explicitly():
    """A silent driver default is how Infisical — the secrets vault — talked to
    its backing store in cleartext: no sslmode was set, and node-postgres
    defaults to SSL OFF where libpq would have upgraded."""
    for rel, key, _value, _why, count in CLIENTS:
        lines = _client_lines(rel, key)
        assert len(lines) == count, (
            f"{rel} should declare {key} exactly {count}×, found {len(lines)} — "
            "a client that lost its connection string falls back to its driver's "
            "default, which is what this gate exists to forbid")
        for line in lines:
            assert "sslmode" in line.lower() or key == "PGSSLMODE", (
                f"{rel} {key} carries no sslmode: {line.strip()[:80]}")


def test_the_server_tls_branch_encrypts_and_never_merely_prefers():
    offenders: list[str] = []
    for rel, key, value, why, _count in CLIENTS:
        for line in _client_lines(rel, key):
            # The `else` arm may still be permissive — that branch is Linux,
            # where the server offers no TLS and an encrypting mode cannot
            # connect at all. Only the server-TLS half is judged.
            head = line.split("else")[0]
            # Matched as a WORD, not as a quoted literal: infisical spells its
            # value inside a longer string (`'?sslmode=no-verify'`), and the
            # first cut of this check reported the vault as an offender for
            # having the right value in the wrong quotes.
            if not re.search(rf"(?<![\w-]){re.escape(value)}(?![\w-])", head):
                offenders.append(f"{rel} {key}: expected {value} on the TLS branch ({why})")
            for weak in PERMITS_PLAINTEXT:
                if re.search(rf"(?<![\w-]){weak}(?![\w-])", head):
                    offenders.append(
                        f"{rel} {key}: {weak} on the server-TLS branch permits "
                        "a plaintext session")
    assert not offenders, (
        "these clients would be allowed to reach PostgreSQL in cleartext across "
        "the shared docker fabric:\n  " + "\n  ".join(offenders)
        + "\n(REM-217 measured 23 of 42 backends plaintext, the vault among them)")


def test_the_conditional_is_gated_on_a_resolvable_variable():
    """The whole reason the old gate was green while the estate was cleartext.
    Every client conditional keys on `postgresql_ssl_enabled`; if that name is
    not at play scope, each of them silently takes the permissive branch."""
    import yaml
    cfg = yaml.safe_load((REPO / "default.config.yml").read_text()) or {}
    assert "postgresql_ssl_enabled" in cfg, (
        "postgresql_ssl_enabled must be declared in default.config.yml. As a "
        "pazny.postgresql role default it is invisible to the seven client "
        "roles that read it, and all seven fall through to plaintext")
    for rel, key, _value, _why, _count in CLIENTS:
        for line in _client_lines(rel, key):
            assert "postgresql_ssl_enabled" in line, (
                f"{rel} {key} decides its sslmode without consulting "
                "postgresql_ssl_enabled — on Linux the server offers no TLS and "
                "an unconditional encrypting mode cannot connect")
