"""A visitor who types the host's IP lands on the face, not a 404.

Traefik routes by name; http(s)://<host ip> answered 404 on spark1
(2026-10-19), the first address a LAN visitor tries. The bare-IP routers
redirect to face_domain, one per entrypoint (a router with tls matches only
TLS), and the web entrypoint's blanket https redirect sits BELOW them by
priority, so http://<ip> is not sent into a certificate warning first.

The gate renders the three templates and reads the YAML Traefik would read,
so a template condition that drops the routers is caught, not just the text.
"""
from __future__ import annotations

import json
import pathlib

import jinja2
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
T = REPO / "roles" / "pazny.traefik" / "templates"


def _render(path: pathlib.Path, **ctx) -> dict:
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined, extensions=["jinja2.ext.do"])
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = lambda v: str(v).lower() in ("true", "1", "yes") if not isinstance(v, bool) else v
    env.globals["lookup"] = lambda _kind, _name, default=None: default
    base = {"nos_manifest": {"services": []}, "traefik_auth_modes": {}, "tenant_domain": "spark.internal",
            "face_domain": "os.spark.internal", "ansible_managed": "test"}
    return yaml.safe_load(env.from_string(path.read_text()).render(**{**base, **ctx})) or {}


def _routers(**ctx) -> dict:
    return ((_render(T / "dynamic" / "services.yml.j2", **ctx).get("http") or {}).get("routers")) or {}


def test_both_entrypoints_route_a_bare_ip_to_the_face():
    r = _routers(install_face=True)
    web, sec = r.get("bare-ip-to-face-web"), r.get("bare-ip-to-face-websecure")
    assert web and sec, f"rendered routers: {sorted(r)}"
    assert web["entryPoints"] == ["web"] and "tls" not in web, "an http router must not demand TLS"
    assert sec["entryPoints"] == ["websecure"] and "tls" in sec
    for x in (web, sec):
        assert x["middlewares"] == ["bare-ip-to-face@file"] and x["rule"].startswith("HostRegexp(`^[0-9]+")
    mw = _render(T / "dynamic" / "middlewares.yml.j2")["http"]["middlewares"]["bare-ip-to-face"]["redirectRegex"]
    assert mw["replacement"] == "https://os.spark.internal/"


def test_no_face_no_redirect_and_the_switch_turns_it_off():
    assert not any(k.startswith("bare-ip") for k in _routers(install_face=False))
    assert not any(k.startswith("bare-ip") for k in _routers(install_face=True, traefik_bare_ip_redirect=False))


def test_the_blanket_https_redirect_yields_to_it():
    static = _render(T / "traefik.yml.j2")
    blanket = static["entryPoints"]["web"]["http"]["redirections"]["entryPoint"]["priority"]
    assert blanket < _routers(install_face=True)["bare-ip-to-face-web"]["priority"]
