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

  4. AND A CLIENT WHOSE URL CANNOT CARRY THE SETTING AT ALL must not pretend
     otherwise. HedgeDoc's `?sslmode=` rendered correctly, resolved correctly,
     and was then picked out of `dialectOptions` by a Sequelize allow-list that
     holds `ssl` and not `sslmode` — so it read as encryption while being the
     one plaintext backend of forty. Those clients are in `OUT_OF_BAND`: the
     URL is required to stay CLEAN and the real control is checked where it
     lives. A dead pin that reads as a control is the shape of hidden fee 23.

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
#:
#: AND THERE IS A THIRD CASE, learned by breaking Outline on 2026-08-23. The
#: contract belongs to WHOEVER PARSES THE STRING, which is not always the
#: driver. Outline reads PGSSLMODE itself, validates it against the LIBPQ enum
#: — so `no-verify`, correct for raw node-postgres, is rejected outright and
#: the container restart-loops — and then maps every value except `disable` to
#: `rejectUnauthorized: false`. Classifying it by its runtime (Node) instead of
#: by its parser is what got it wrong.
CLIENTS = (
    ("roles/pazny.authentik/templates/compose.yml.j2", "AUTHENTIK_POSTGRESQL__SSLMODE",
     "require", "psycopg → libpq", 2),
    ("roles/pazny.paperclip/templates/compose.yml.j2", "DATABASE_URL",
     "require", "libpq-family: negotiated TLS under prefer", 1),
    ("roles/pazny.miniflux/templates/compose.yml.j2", "DATABASE_URL",
     "require", "Go lib/pq → libpq semantics; live TLS under prefer", 1),
    ("roles/pazny.grafana/templates/compose.yml.j2", "DATA_SOURCE_NAME",
     "require", "postgres_exporter, Go lib/pq", 1),
    ("roles/pazny.outline/templates/compose.yml.j2", "PGSSLMODE",
     "require", "Outline OWNS this string: validates the libpq enum (no-verify "
     "is rejected, restart-looped 2026-08-23) then maps everything except "
     "`disable` to rejectUnauthorized:false itself", 1),
    ("roles/pazny.infisical/templates/compose.yml.j2", "DB_CONNECTION_URI",
     "no-verify", "knex → node-postgres; had NO sslmode at all, the vault in clear", 1),
)

#: Where the APPLICATION validates the value itself, its accepted set — copied
#: from the validator's own error message, which is the authoritative list.
#:
#: Only Outline is here because only Outline has been observed refusing. The
#: point is not coverage; it is that a value which an application will reject
#: must fail in this file rather than in a restart loop at 03:00. Add an entry
#: the first time a service names its enum, and never guess one: an invented
#: set that is too NARROW blocks a correct value, which is worse than no check.
ACCEPTED = {
    "roles/pazny.outline/templates/compose.yml.j2": (
        "disable", "allow", "require", "prefer", "verify-ca", "verify-full",
    ),
}

#: Values that permit a plaintext session. `prefer` is here on evidence, not on
#: principle: under `prefer` the estate measured 22 cleartext Authentik backends
#: against a server with ssl=on.
PERMITS_PLAINTEXT = ("disable", "prefer", "allow")

#: Clients whose connection string CANNOT carry the setting at all, so pinning
#: one there is decoration. They are held to a stricter rule than CLIENTS: the
#: URL must stay CLEAN, and the real control is checked where it lives.
#:
#: HedgeDoc is the whole membership. Its URL reached Sequelize 5.22.5, which
#: parses the query into `dialectOptions` and then copies dialectOptions into pg
#: through `_.pick([... 'ssl' ...])` — a list without `sslmode`. So the value
#: was not misread, it was dropped, and `tools/tls-uptake.py` measured this one
#: backend of forty in cleartext for the eight hours the "fix" was live.
OUT_OF_BAND = {
    "roles/pazny.hedgedoc/templates/compose.yml.j2": {
        "key": "CMD_DB_URL",
        "control": "roles/pazny.hedgedoc/templates/config.json.j2",
        "mount": "/hedgedoc/config.json",
    },
}


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


def test_a_value_the_application_itself_validates_is_in_its_accepted_set():
    """Outline restart-looped on 2026-08-23 with

        PGSSLMODE must be one of the following values:
        disable, allow, require, prefer, verify-ca, verify-full

    `no-verify` — correct for raw node-postgres — is not in Outline's list,
    because Outline parses the variable itself and validates against libpq's
    enum. BOTH branches are checked: the `else` arm ships on Linux, where a
    restart loop would be found by CI rather than by an operator."""
    for rel, key, value, _why, _count in CLIENTS:
        accepted = ACCEPTED.get(rel)
        if not accepted:
            continue
        for line in _client_lines(rel, key):
            rendered = re.findall(r"'([a-z-]+)'", line)
            assert rendered, f"{rel} {key}: no literal value to check: {line.strip()[:80]}"
            for candidate in rendered:
                assert candidate in accepted, (
                    f"{rel} {key} renders {candidate!r}, which the application "
                    f"refuses at startup — it accepts only {', '.join(accepted)}. "
                    "This is not a driver question: the application parses the "
                    "variable before any driver sees it")


def _render(rel: str, **ctx) -> str:
    import jinja2
    path = REPO / rel
    # trim_blocks matches ansible.builtin.template's own default. A gate that
    # renders with different settings than the renderer under test is checking
    # a string the estate never produces — the recurring shape here.
    env = jinja2.Environment(  # noqa: S701 — rendering our own template, not user input
        loader=jinja2.FileSystemLoader(str(path.parent)),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    return env.get_template(path.name).render(**ctx)


def test_a_client_that_cannot_carry_sslmode_does_not_pretend_to():
    """The URL must stay clean where the URL is not the control.

    Re-adding `?sslmode=...` here would be harmless at runtime and expensive
    the next time somebody reads it: it is the exact line that read as
    encryption for eight hours while the backend was in cleartext."""
    for rel, spec in OUT_OF_BAND.items():
        for line in _client_lines(rel, spec["key"]):
            assert "sslmode" not in line.lower(), (
                f"{rel} {spec['key']} carries an sslmode again. Sequelize's "
                "postgres dialect picks `ssl` out of dialectOptions and drops "
                f"everything else — the control is {spec['control']}")
            assert "?ssl=" not in line and "&ssl=" not in line, (
                f"{rel} {spec['key']} carries ?ssl= — a query value is a STRING, "
                "and pg spreads a non-`true` ssl with Object.assign, leaving "
                "rejectUnauthorized at Node's default TRUE: the self-signed "
                "server cert would be REFUSED and the container would not start")


def test_the_out_of_band_control_encrypts_on_the_tls_branch():
    import json
    for rel, spec in OUT_OF_BAND.items():
        on = json.loads(_render(spec["control"], postgresql_ssl_enabled=True))
        # Keyed by NODE_ENV upstream (lib/config/index.js:14/35). A file keyed
        # for the wrong env is READ, ignored, and reports nothing — so both
        # keys are required rather than assumed.
        assert set(on) >= {"production", "development"}, (
            f"{spec['control']} must key its block by NODE_ENV for every env "
            "HedgeDoc can start in; a wrongly-keyed file is silently ignored")
        for env_name, block in on.items():
            ssl = block["db"]["dialectOptions"]["ssl"]
            assert isinstance(ssl, dict), (
                f"{spec['control']}[{env_name}] sets ssl to {ssl!r}. It must be "
                "an OBJECT: pg does `Object.assign(options, this.ssl)` for any "
                "value that is not literally true, so a string spreads into "
                "character keys and verification stays ON")
            assert ssl.get("rejectUnauthorized") is False, (
                f"{spec['control']}[{env_name}] would verify the CA against a "
                "role-generated SELF-SIGNED cert — the connection fails closed")


def test_the_out_of_band_control_is_inert_when_the_server_offers_no_tls():
    """Linux ships without server TLS. A config that demands SSL there is not
    a weaker guarantee, it is a service that cannot connect at all."""
    import json
    for rel, spec in OUT_OF_BAND.items():
        off = json.loads(_render(spec["control"], postgresql_ssl_enabled=False))
        assert off == {}, (
            f"{spec['control']} still asks for SSL with the server TLS branch "
            f"off: {off!r}")


def test_the_out_of_band_control_is_mounted_where_the_application_reads_it():
    """A rendered file nothing mounts is the same defect one layer along."""
    for rel, spec in OUT_OF_BAND.items():
        src = (REPO / rel).read_text()
        mount = [ln for ln in src.splitlines() if spec["mount"] in ln]
        assert mount, (
            f"{rel} renders {spec['control']} but never mounts it at "
            f"{spec['mount']} — the application would read the image's empty "
            "default and connect in cleartext, saying nothing")
        assert all(ln.rstrip().endswith(":ro") for ln in mount), (
            f"{rel}: {spec['mount']} must mount read-only")
        assert "postgresql_ssl_enabled" in src, (
            f"{rel} mounts the TLS config unconditionally; on a host whose "
            "server offers no TLS the container would fail to connect")
