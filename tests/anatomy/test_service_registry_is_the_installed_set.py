"""The service registry lists what this host installed — every such service, nothing else.

MEASURED 2026-10-15 on a client host converged with profiles/core.yml: it runs
keap, face and traefik, yet templates/service-registry.json.j2 (its own hand
list of `{% if install_x %}` blocks) had no entry for them, so Wing /hub and
the face dock offered Authentik and Wing only. The registry is RENDERED here;
the expected set is nos_identity.installed(), the services-status derivation.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "tools"), str(REPO / "files/anatomy")]
import nos_identity as ni  # noqa: E402
from module_utils import load_plugins as lp  # noqa: E402

TEMPLATE = REPO / "templates/service-registry.json.j2"
FILTER = REPO / "filter_plugins/nos_installed.py"
#: Traefik routes no host for these (roles/pazny.traefik/vars/main.yml); traefik's
#: own dashboard is the separate SSO-gated router, so it keeps its card.
SKIP = set(yaml.safe_load((REPO / "roles/pazny.traefik/vars/main.yml").read_text())["traefik_skip_ids"]) - {"traefik"}

#: Host nginx and its exporters: installed by install_nginx, no manifest row.
HOST_PACKAGES = {"nginx", "phpfpm", "nginx_exporter", "phpfpm_exporter"}


def _flags(profile: str) -> dict:
    layers = ni.profile_layers(REPO / "profiles" / profile)
    return {**ni.install_flags(layers), "redis_docker": ni.resolve_flag("redis_docker", layers)[-1][1]}


def render(flags: dict) -> list[dict]:
    """The registry's services for `flags`, rendered as Ansible would."""
    env = lp._jinja_env()
    env.undefined = jinja2.ChainableUndefined
    if FILTER.is_file():
        spec = importlib.util.spec_from_file_location("nos_installed", FILTER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        env.filters.update(mod.FilterModule().filters())
    ctx = dict(flags, tenant_domain="dev.local", playbook_dir=str(REPO),
               ansible_facts={"hostname": "h", "env": {"HOME": "/h"}})
    ctx["lookup"] = lambda kind, name, default=None: (
        Path(name).read_text(encoding="utf-8") if kind == "file" else ctx.get(name, default))
    return json.loads(env.from_string(TEMPLATE.read_text(encoding="utf-8")).render(ctx))["services"]


def _with_ui(services: list[dict]) -> set[str]:
    return {s["id"] for s in services if s.get("url")}


def _installed_ui(flags: dict) -> set[str]:
    return {r["id"] for r in ni.installed(flags) if r.get("domain_var") and r["id"] not in SKIP}


def test_core_registry_lists_its_installed_services_with_a_ui() -> None:
    got = _with_ui(render(_flags("core.yml")))
    assert got == {"authentik", "face", "keap", "traefik", "wing"}, (
        f"core host: registry cards {sorted(got)}; a core hub must offer exactly what core runs")


def test_registry_is_the_installed_set() -> None:
    for profile in ("core.yml", "all-on.yml"):
        flags = _flags(profile)
        services = render(flags)
        installed = {r["id"] for r in ni.installed(flags)}
        stray = sorted({s["id"] for s in services} - installed - HOST_PACKAGES)
        assert not stray, f"{profile}: registry lists {stray}, not installed rows"
        assert _with_ui(services) == _installed_ui(flags), (
            f"{profile}: registry cards differ from installed UIs: "
            f"missing {sorted(_installed_ui(flags) - _with_ui(services))}, "
            f"extra {sorted(_with_ui(services) - _installed_ui(flags))}")


def test_a_service_switched_off_disappears() -> None:
    flags = dict(_flags("core.yml"), install_keap=False)
    assert "keap" not in {s["id"] for s in render(flags)}
