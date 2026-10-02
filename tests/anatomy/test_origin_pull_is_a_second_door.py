"""Anatomy gate — Cloudflare Authenticated Origin Pulls is a SECOND door.

sec-origin-answers-anyone (2026-09-03): 4669 no-router requests/24h straight to
the origin; Docker NAT hides every source, so only mTLS can tell CF apart.
The door is `websecure-origin`; :443 stays as it was. Runbook + red-proofs:
docs/traefik-primary-proxy.md §Cloudflare origin pulls.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "roles" / "pazny.traefik"
CA = ROLE / "files" / "cloudflare-origin-pull-ca.crt"
CA_IN_CONTAINER = "/etc/traefik/cloudflare-origin-pull-ca.crt"
OPTION = "origin-pull@file"

SERVICES = "roles/pazny.traefik/templates/dynamic/services.yml.j2"
STATIC = "roles/pazny.traefik/templates/traefik.yml.j2"
COMPOSE = "roles/pazny.traefik/templates/compose.yml.j2"
ORIGIN = "roles/pazny.traefik/templates/dynamic/origin-pull.yml.j2"
KEAP = ["roles/pazny.keap/templates/traefik-ext.yml.j2",
        "roles/pazny.keap/templates/traefik-ingest.yml.j2"]
STALWART = "roles/pazny.smtp_stalwart/templates/compose.yml.j2"
EMITTERS = [SERVICES, STATIC, COMPOSE, STALWART, *KEAP]


def _bool(v):
    return v.strip().lower() in ("true", "1", "yes", "on") if isinstance(v, str) else bool(v)


def _env(**kw) -> jinja2.Environment:
    e = jinja2.Environment(undefined=jinja2.ChainableUndefined, **kw)
    e.filters.update(bool=_bool, to_json=json.dumps,
                     regex_replace=lambda s, p, r: re.sub(p, r.replace("\\1", "\\g<1>"), s))
    return e


def _ctx(**over) -> dict:
    """default.config + traefik role vars, every install_* on, a public TLD."""
    c = yaml.safe_load((REPO / "default.config.yml").read_text())
    c.update(yaml.safe_load((ROLE / "defaults" / "main.yml").read_text()))
    c.update(yaml.safe_load((ROLE / "vars" / "main.yml").read_text()))
    c.update({k: True for k in c if k.startswith("install_")})
    c.update(tenant_domain="example.eu", tenant_domain_is_local=False, _host_alias_seg="",
             traefik_dashboard_route_enabled=True, stacks_dir="/stacks", ansible_managed="m",
             traefik_networks=["infra_net", "shared_net"])
    c.pop("traefik_origin_pull_enabled", None)
    c.update(over)
    e = _env()
    for _ in range(3):
        for k, v in list(c.items()):
            if isinstance(v, str) and "{{" in v:
                try:
                    c[k] = e.from_string(v).render(c)
                except Exception:  # noqa: BLE001 — leave unresolvable raw
                    pass
    c["nos_manifest"] = yaml.safe_load((REPO / "state" / "manifest.yml").read_text())
    c["lookup"] = lambda kind, name, default=None, **kw: c.get(name, default)
    return c


def render(rel: str, **over) -> str:
    env = _env(trim_blocks=True, lstrip_blocks=False, keep_trailing_newline=True)
    return env.from_string((REPO / rel).read_text()).render(_ctx(**over))


def tier2(origin_pull: bool) -> dict[str, list[str]]:
    sys.path.insert(0, str(REPO / "files" / "anatomy" / "library"))
    sys.path.insert(0, str(REPO / "files" / "anatomy"))
    import nos_apps_render as m
    out = {}
    for p in sorted((REPO / "apps").glob("*.yml")):
        if p.name.startswith("_"):
            continue
        app, _, _ = m._process_one(str(p), "example.eu", "apps", {}, [], False,
                                   "shared_net", origin_pull=origin_pull)
        if app:
            out[app["id"]] = app["traefik_labels"]
    return out


def _labels_to_routers(labels: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for lbl in labels:
        m = re.match(r"traefik\.http\.routers\.([^.]+)\.(.+?)=(.*)$", lbl)
        if m:
            out.setdefault(m[1], {})[m[2]] = m[3]
    return out


def _stalwart_labels(**over) -> list[str]:
    svc = yaml.safe_load(render(STALWART, **over))["services"]
    return [l for s in svc.values() for l in (s.get("labels") or []) if l.startswith("traefik.")]


def file_routers(**over) -> dict[str, dict]:
    routers = dict(yaml.safe_load(render(SERVICES, **over))["http"]["routers"])
    for k in KEAP:
        routers.update(yaml.safe_load(render(k, **over))["http"]["routers"])
    return routers


def docker_routers(origin_pull: bool) -> dict[str, dict]:
    on = {"traefik_origin_pull_enabled": True} if origin_pull else {}
    out = _labels_to_routers(_stalwart_labels(**on))
    for labels in tier2(origin_pull).values():
        out.update(_labels_to_routers(labels))
    return out


# ── off: nothing changes ────────────────────────────────────────────────────
@pytest.mark.parametrize("rel", EMITTERS)
def test_off_renders_byte_identical_and_carries_no_door(rel):
    absent, off = render(rel), render(rel, traefik_origin_pull_enabled=False)
    assert absent == off
    assert "websecure-origin" not in off and "origin-pull" not in off


def test_default_is_off_and_tier2_off_is_unchanged():
    assert yaml.safe_load((REPO / "default.config.yml").read_text())["traefik_origin_pull_enabled"] is False
    assert not any("origin" in l for ls in tier2(False).values() for l in ls)


def test_on_only_adds_never_changes_port_443():
    on = {"traefik_origin_pull_enabled": True}
    fon, foff = file_routers(**on), file_routers()
    assert {k: v for k, v in fon.items() if not k.endswith("-origin")} == foff
    don, doff = docker_routers(True), docker_routers(False)
    assert {k: v for k, v in don.items() if not k.endswith("-origin")} == doff
    eon = yaml.safe_load(render(STATIC, **on))["entryPoints"]
    assert {k: v for k, v in eon.items() if k != "websecure-origin"} == yaml.safe_load(render(STATIC))["entryPoints"]


# ── on: every websecure router has a twin behind mTLS ───────────────────────
@pytest.mark.parametrize("kind", ["file", "docker"])
def test_every_websecure_router_has_an_origin_twin(kind):
    routers = file_routers(traefik_origin_pull_enabled=True) if kind == "file" else docker_routers(True)
    ep = "entryPoints" if kind == "file" else "entrypoints"
    as_list = (lambda v: v) if kind == "file" else (lambda v: v.split(","))
    front = {n: r for n, r in routers.items() if as_list(r.get(ep, [])) == ["websecure"]}
    assert front, "no websecure router rendered — the harness is broken, not the estate"
    for name, r in front.items():
        twin = routers.get(name + "-origin")
        assert twin, f"{kind} router {name!r} has no websecure-origin twin"
        assert as_list(twin[ep]) == ["websecure-origin"], name
        for key in ("rule", "middlewares", "priority"):
            assert twin.get(key) == r.get(key), f"{name}-origin {key} differs from {name}"
        if kind == "file":
            assert twin["service"] == r["service"], name
    # A router on the door WITHOUT the option makes the host's TLS options
    # conflict, and Traefik then falls back to `default` — fail-open.
    door = {n: r for n, r in routers.items() if "websecure-origin" in as_list(r.get(ep, []))}
    for name, r in door.items():
        opt = (r.get("tls") or {}).get("options") if kind == "file" else r.get("tls.options")
        assert opt == OPTION, f"{name} is on websecure-origin without {OPTION}"


def test_tier2_runner_passes_the_flag():
    tasks = (REPO / "roles" / "pazny.apps_runner" / "tasks" / "main.yml").read_text()
    assert re.search(r"origin_pull:\s*\"\{\{\s*traefik_origin_pull_enabled", tasks)


def test_door_is_published_and_hardened_like_443():
    on = {"traefik_origin_pull_enabled": True, "traefik_origin_pull_port": 9443}
    static = yaml.safe_load(render(STATIC, **on))
    assert static["core"]["strictTLSOptions"] is True  # a TLS-option conflict disables, never downgrades
    eps = static["entryPoints"]
    door = eps["websecure-origin"]
    assert door["address"] == ":8443"
    front = dict(eps["websecure"]["http"])
    front.pop("tls")  # modern@file is the :443 model; the door's routers name their own
    assert door["http"] == front and door.get("forwardedHeaders") == eps["websecure"].get("forwardedHeaders")
    ports = yaml.safe_load(render(COMPOSE, **on))["services"]["traefik"]["ports"]
    assert "9443:8443" in ports


def test_the_option_requires_and_verifies_the_vendored_ca():
    doc = yaml.safe_load(render(ORIGIN, traefik_origin_pull_enabled=True))
    opt = doc["tls"]["options"]["origin-pull"]
    assert opt["clientAuth"] == {"caFiles": [CA_IN_CONTAINER],
                                 "clientAuthType": "RequireAndVerifyClientCert"}
    assert opt["sniStrict"] is True
    # The catch-all: an SNI matching no router must not fall to `default`.
    tcp = doc["tcp"]["routers"]["origin-pull-refuse"]
    assert tcp["rule"] == "HostSNI(`*`)" and tcp["entryPoints"] == ["websecure-origin"]
    assert tcp["tls"] == {"options": OPTION}
    # The CA reaches that path: copied into traefik_config_dir, mounted at /etc/traefik.
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    copy = next(t for t in tasks if "ansible.builtin.copy" in t)["ansible.builtin.copy"]
    assert copy["src"] == CA.name
    assert copy["dest"] == "{{ traefik_config_dir }}/" + Path(CA_IN_CONTAINER).name
    vols = yaml.safe_load(render(COMPOSE))["services"]["traefik"]["volumes"]
    assert f"{_ctx()['traefik_config_dir']}:/etc/traefik:ro" in vols


# ── on + local TLD = refused ────────────────────────────────────────────────
def _refusal():
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    return next(t for t in tasks if "ansible.builtin.assert" in t
                and "traefik_origin_pull_enabled" in str(t.get("when")))


@pytest.mark.parametrize("local, passes", [(True, False), (False, True)])
def test_local_tld_is_refused(local, passes):
    t = _refusal()
    ctx = _ctx(traefik_origin_pull_enabled=True, tenant_domain_is_local=local)
    e = _env()
    fires = e.from_string("{{ " + t["when"] + " }}").render(ctx) == "True"
    ok = all(e.from_string("{{ " + c + " }}").render(ctx) == "True"
             for c in t["ansible.builtin.assert"]["that"])
    assert fires and ok is passes


# ── the vendored CA is Cloudflare's CA ──────────────────────────────────────
def test_vendored_ca_is_cloudflares_origin_pull_ca():
    # The header records the DER sha256 measured against Cloudflare's published
    # PEM on the fetch date; the body must still hash to it.
    text = CA.read_text()
    pin = re.search(r"^DER sha256 ([0-9a-f]{64})", text, re.M)[1]
    body = re.search(r"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", text, re.S)[1]
    assert hashlib.sha256(base64.b64decode(body)).hexdigest() == pin
    if not shutil.which("openssl"):
        pytest.skip("openssl absent — DER pin above still held")
    text = subprocess.run(["openssl", "x509", "-in", str(CA), "-noout", "-text"],
                          capture_output=True, text=True, check=True).stdout
    assert "CA:TRUE" in text and "Certificate Sign" in text
    assert "CN=origin-pull.cloudflare.net" in text.replace(" = ", "=")
    assert subprocess.run(["openssl", "x509", "-in", str(CA), "-noout", "-checkend", "0"]).returncode == 0
