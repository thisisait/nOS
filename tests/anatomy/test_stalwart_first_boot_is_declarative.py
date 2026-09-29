"""Stalwart's first boot is a rendered plan, not a wizard.

Measured 2026-09-28: the server had run in bootstrap mode since 2026-07-22
("No configuration file was found"), /etc/stalwart empty, only the recovery
listener up, the STRICT wait admitting it as "SMTP not in test scope". The
compose comment said STALWART_RECOVERY_ADMIN "skips the WebUI wizard"; it pins
the wizard's login. This gate RENDERS what the role now ships and checks it is
a plan a server can apply, that the store config exists, that the CLI is
pinned by digest, and that the post-start proves the effect with a banner.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "roles/pazny.smtp_stalwart"
VARS = dict(tenant_domain="example.eu", stalwart_domain="mail.example.eu",
            stalwart_dkim_selector="nos-ed25519", stalwart_dns_automatic=True,
            acme_cloudflare_api_token="cf-token", stalwart_admin_username="admin",
            stalwart_admin_password="pw")


def _render(name: str, **over) -> list[dict]:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, trim_blocks=False)
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = lambda v: v in (True, "true", "True", "1", 1)
    text = env.from_string((ROLE / "templates" / name).read_text()).render({**VARS, **over})
    # NDJSON: ONE object per line. The CLI refused a listener upsert that was
    # split over lines for readability ("invalid plan NDJSON on line 5").
    objs = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    # forward references: an object may only point (#key) at a key on an EARLIER
    # line — the bootstrap plan's Account came before its Domain and failed.
    seen: set[str] = set()
    for o in objs:
        refs = set(re.findall(r'"#([a-z]+)"', json.dumps(o)))
        assert refs <= seen, f"{name}: {o['object']} references {refs - seen} before it is defined"
        seen |= set((o.get("value") or {}).keys())
    return objs


def test_config_json_names_only_the_store():
    cfg = json.loads((ROLE / "templates/config.json.j2").read_text())
    assert cfg == {"@type": "RocksDb", "path": "/var/lib/stalwart/"}


def test_the_plan_is_valid_ndjson_and_covers_every_published_port():
    objs = _render("plan.ndjson.j2")
    by = {o["object"]: o for o in objs}
    listeners = by["NetworkListener"]["value"]
    ports = {int(next(iter(v["bind"])).rsplit(":", 1)[1]) for v in listeners.values()}
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    published = {defaults[k] for k in ("stalwart_port_smtp", "stalwart_port_smtps",
                                       "stalwart_port_submission", "stalwart_port_imap")}
    assert published <= ports, f"listeners {ports} do not cover published {published}"
    assert 8080 in ports, "no http listener on 8080 — Wing's JMAP and the admin UI have no door"
    assert by["DkimSignature"]["value"]["dkim"]["domainId"] == "#dom"
    assert by["Domain"]["value"]["dom"]["dnsManagement"]["@type"] == "Automatic"
    assert by["DnsServer"]["value"]["dns"]["@type"] == "Cloudflare"
    assert by["SystemSettings"]["value"]["defaultHostname"] == "mail.example.eu"
    assert "Certificate" not in by, "Certificate has no label to upsert on — the CLI refused it (invalidPatch: name)"
    cm = by["Domain"]["value"]["dom"]["certificateManagement"]
    assert cm["acmeProviderId"] == "#acme" and cm["subjectAlternativeNames"] == {"mail.example.eu": True}
    assert by["AcmeProvider"]["value"]["acme"]["challengeType"] == "Dns01"


def test_without_a_dns_token_the_domain_is_manual_and_no_secret_renders():
    objs = _render("plan.ndjson.j2", stalwart_dns_automatic=False, acme_cloudflare_api_token="")
    by = {o["object"]: o for o in objs}
    assert "DnsServer" not in by and "AcmeProvider" not in by
    assert by["Domain"]["value"]["dom"]["dnsManagement"] == {"@type": "Manual"}
    assert by["Domain"]["value"]["dom"]["certificateManagement"] == {"@type": "Manual"}


def test_the_bootstrap_plan_holds_the_admin_and_nothing_re_hashes_nightly():
    boot = {o["object"]: o for o in _render("bootstrap-plan.ndjson.j2")}
    acct = boot["Account"]["value"]["admin"]
    assert acct["roles"] == {"@type": "Admin"} and acct["credentials"]["0"]["secret"] == "pw"
    main = {o["object"] for o in _render("plan.ndjson.j2")}
    assert "Account" not in main, "a Password credential in the idempotent plan re-hashes on every apply"


def test_the_cli_is_pinned_by_digest_and_the_effect_is_read_not_assumed():
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert re.fullmatch(r"ghcr\.io/stalwartlabs/cli@sha256:[0-9a-f]{64}", defaults["stalwart_cli_image"])
    post = yaml.safe_load((ROLE / "tasks/post.yml").read_text())
    banner = [t for t in post if "220 banner" in t["name"]][0]
    assert "220*" in banner["ansible.builtin.shell"] and banner.get("changed_when") is False
    assert not banner.get("failed_when"), "the banner read must be allowed to fail the play"
    apply = [t for t in post if t["name"].endswith("(idempotent upserts)")][0]
    assert "created" in apply["changed_when"] and "updated" not in apply["changed_when"], (
        "an upsert reports updated on every apply; changed must key on created")
    core = (REPO / "tasks/stacks/core-up.yml").read_text()
    assert core.index("pazny.smtp_stalwart post-start") < core.index("Wait for INFRA stack healthy"), (
        "the apply must run before the STRICT wait, or a first boot in recovery mode can never pass it")


def test_the_plan_allow_lists_the_estate_and_a_converge_lifts_a_self_ban():
    """Stalwart banned the Docker Desktop gateway (192.168.65.1) for "port
    scanning" two minutes after its first boot — permanently — and the host's
    banner probe hung (2026-09-29). Every host-originated connection carries
    that one address, so the plan must allow the estate's own space and the
    post-start must lift a ban already written (the plan cannot undo one)."""
    import ipaddress
    import subprocess
    objs = _render("plan.ndjson.j2")
    allowed = [ipaddress.ip_network(v["address"]) for o in objs if o["object"] == "AllowedIp"
               for v in o["value"].values()]
    for ip in ("127.0.0.1", "192.168.65.1", "172.20.0.1", "::1"):
        assert any(ipaddress.ip_address(ip) in n for n in allowed), f"{ip} not allow-listed"
    # The server stores a single host WITHOUT its /32 or /128: "::1/128" was
    # upserted, matched nothing, and the create hit primaryKeyViolation on the
    # second converge (2026-09-29). Write it the way the server keys it.
    raw = [v["address"] for o in objs if o["object"] == "AllowedIp" for v in o["value"].values()]
    for a in raw:
        assert ipaddress.ip_network(a).num_addresses > 1 or "/" not in a, f"{a}: a host address must carry no prefix"
    tasks = yaml.safe_load((ROLE / "tasks/post.yml").read_text())
    names = [t["name"] for t in tasks]
    lift = names.index("[pazny.smtp_stalwart] Lift bans on estate-internal addresses")
    assert names.index("[pazny.smtp_stalwart] Apply the plan (idempotent upserts)") < lift < len(names) - 1
    restart = names.index("[pazny.smtp_stalwart] Restart so the in-memory ban list forgets the host")
    assert lift < restart < len(names) - 1, "the restart must follow the unban and precede the fatal banner reader"
    # Run the filter itself against a public and a private ban: only the private id may be lifted.
    src = tasks[lift]["ansible.builtin.shell"]
    py = src.split("python3 -c '", 1)[1].split("\n')", 1)[0]
    rows = '[{"id":"pub","address":"8.8.8.8"},{"id":"gw","address":"192.168.65.1"}]'
    out = subprocess.run(["python3", "-c", py], input=rows, capture_output=True, text=True, check=True).stdout
    assert out.strip() == "gw", out
    assert "STALWART_PASSWORD {{" in src and "no_log" not in src and tasks[lift]["no_log"] is True
