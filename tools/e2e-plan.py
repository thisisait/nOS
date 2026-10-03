#!/usr/bin/env python3
"""What the estate promises a user, rendered from the manifests — the E2E plan.

One source of truth: each plugin's `authentik:` block already says how a person
reaches the service (mode, tier, client, redirect, launch URL, enabled), and an
optional `e2e:` block says what "wired" means after start. This renders both
against the SAME resolved config nos-smoke probes (tools/nos-smoke.py
load_vars: defaults → config.yml → ~/.nos/state.yml → domain helpers), so a
journey can never be written for a service the configuration does not run.

  tools/e2e-plan.py                 # JSON plan of the enabled services
  tools/e2e-plan.py --all           # include disabled ones (enabled: false)
"""
from __future__ import annotations

import argparse
import getpass
import importlib.util
import json
import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[1]
PLUGINS = REPO / "files/anatomy/plugins"
MODES = ("native_oidc", "forward_auth", "header_oidc")

_spec = importlib.util.spec_from_file_location("nos_smoke", REPO / "tools/nos-smoke.py")
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


def _env(vars_: dict) -> jinja2.Environment:
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    env.filters["bool"] = lambda v: str(v).strip().lower() in ("1", "true", "yes", "y", "on")
    env.globals.update(vars_)
    return env


def _render(env: jinja2.Environment, value):
    if isinstance(value, str):
        # Values are templates of templates: gitea_admin_user → nos_primary_admin
        # → ansible_facts.user_id is three deep. Render to a fixed point.
        out = value
        for _ in range(5):
            if "{{" not in out:
                break
            out = env.from_string(out).render()
        return out
    if isinstance(value, list):
        return [_render(env, v) for v in value]
    if isinstance(value, dict):
        return {k: _render(env, v) for k, v in value.items()}
    return value


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _role_defaults() -> dict:
    """Role defaults sit UNDER every vars file in Ansible's precedence; the
    smoke layering never read them, so backrest_domain rendered `https://`."""
    out: dict = {}
    for f in sorted(REPO.glob("roles/pazny.*/defaults/main.yml")):
        out.update(yaml.safe_load(f.read_text(encoding="utf-8")) or {})
    return out


def _edge_modes() -> dict:
    """What Traefik actually puts in front of a service: proxy = the Authentik
    forward-auth middleware, oidc/none = nothing. Absent keys fall through to
    proxy (roles/pazny.traefik/templates/services.yml.j2)."""
    v = yaml.safe_load((REPO / "roles/pazny.traefik/vars/main.yml").read_text(encoding="utf-8")) or {}
    return v.get("traefik_auth_modes") or {}


def _manifest_domains() -> dict:
    rows = (yaml.safe_load((REPO / "state/manifest.yml").read_text(encoding="utf-8")) or {}).get("services", [])
    return {r["id"]: r["domain_var"] for r in rows if r.get("id") and r.get("domain_var")}


def _host(url) -> str:
    return (str(url or "").split("://", 1)[-1].split("/", 1)[0]).strip()


def _resolved(vars_: dict | None) -> tuple[dict, jinja2.Environment]:
    vars_ = {**_role_defaults(), **(smoke.load_vars() if vars_ is None else vars_)}
    # The facts the playbook would have: gitea_admin_user is nos_primary_admin
    # is ansible_facts.user_id, so without them the repo owner rendered "".
    vars_.setdefault("ansible_facts", {"user_id": getpass.getuser(),
                                       "env": {"HOME": str(Path.home())},
                                       "os_family": "Darwin" if sys.platform == "darwin" else "Debian"})
    # A templated var seen from INSIDE another template is its raw text, so
    # `if tenant_domain_is_local` was always truthy; pin bool-valued ones first.
    env = _env(vars_)
    for k, v in list(vars_.items()):
        if isinstance(v, str) and "{{" in v:
            try:
                out = _render(env, v)
            except jinja2.TemplateError:     # Ansible-only filters: leave as is
                continue
            if out in ("True", "False"):
                vars_[k] = out == "True"
    return vars_, _env(vars_)


def identities(vars_: dict | None = None) -> list[dict]:
    """nos_identities as this config resolves them. An entry whose enabled_by
    toggle is off has no account anywhere, so it is not returned."""
    vars_, env = _resolved(vars_)
    return [_render(env, i) for i in vars_.get("nos_identities") or []
            if isinstance(i, dict) and (not i.get("enabled_by")
                                        or _truthy(_render(env, vars_.get(i["enabled_by"], False))))]


def plan(vars_: dict | None = None, include_disabled: bool = False) -> list[dict]:
    vars_, env = _resolved(vars_)
    edge, domains = _edge_modes(), _manifest_domains()
    rows = []
    for path in sorted(PLUGINS.glob("*/plugin.yml")):      # discovery, gitleaks carry no -base
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        ak = doc.get("authentik") or {}
        e2e = doc.get("e2e") or {}
        if not ak and not e2e:
            continue
        # client_secret stays unrendered: a plan is not a secrets carrier.
        ak = {k: v for k, v in ak.items() if k != "client_secret"}
        r = _render(env, ak)
        enabled = _truthy(r.get("enabled", _render(env, e2e.get("enabled", "false"))))
        if not enabled and not include_disabled:
            continue
        redirects = r.get("redirect_uris") or []
        key = path.parent.name.removesuffix("-base").replace("-", "_")
        launch = r.get("launch_url")
        if not launch and key in domains:       # metabase, woodpecker declare none
            launch = "https://" + _render(env, "{{ " + domains[key] + " }}")
        rows.append({
            "plugin": path.parent.name,
            "slug": r.get("slug") or path.parent.name.removesuffix("-base"),
            "name": r.get("name"),
            "mode": r.get("mode") if r.get("mode") in MODES else None,
            "tier": int(r["tier"]) if str(r.get("tier", "")).isdigit() else None,
            "client_id": r.get("client_id"),
            "redirect_uri": redirects[0] if redirects else None,
            "launch_url": launch,
            # Where a first SSO login creates the account: the app's own button,
            # or for header_oidc the launch URL (the proxy headers provision).
            "first_login": r.get("first_login") or (launch if r.get("mode") == "header_oidc" else None),
            "first_login_blocked": r.get("first_login_blocked"),
            "edge": edge.get(key, "proxy"),
            "enabled": enabled,
            "probes": _render(env, e2e.get("probes") or []),
            "isolation": _render(env, e2e.get("isolation") or []),
            "app": bool(ak),     # e2e-only plugins (backup, alert-relay) have no URL to open
        })
    # Manifest apps (apps/*.yml) carry their own authentik: block and were
    # invisible to a plugin-only walk: documenso, twofauth, roundcube.
    # Same rendering, same edge rule.
    by_slug = {r["slug"]: r for r in rows}
    skip = set(vars_.get("apps_skip") or [])
    for path in sorted((REPO / "apps").glob("*.yml")):
        if path.name.startswith("_"):
            continue
        ak = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("authentik") or {}
        if not ak:
            continue
        r = _render(env, {k: v for k, v in ak.items() if k != "client_secret"})
        slug = r.get("slug") or path.stem
        enabled = _truthy(vars_.get("apps_runner_enabled", False)) and path.stem not in skip
        if slug in by_slug:
            by_slug[slug]["launch_url"] = by_slug[slug]["launch_url"] or r.get("launch_url")
            continue
        if not enabled and not include_disabled:
            continue
        rows.append({"plugin": f"apps/{path.name}", "slug": slug, "name": r.get("name"),
                     "mode": r.get("mode") if r.get("mode") in MODES else None,
                     "tier": int(r["tier"]) if str(r.get("tier", "")).isdigit() else None,
                     "client_id": r.get("client_id"), "redirect_uri": (r.get("redirect_uris") or [None])[0],
                     "launch_url": r.get("launch_url"), "first_login": r.get("first_login"),
                     "edge": "proxy", "enabled": enabled, "probes": [], "isolation": [], "app": True})
    for row in rows:
        row["unresolved"] = [k for k in ("launch_url", "redirect_uri")
                             if (row[k] is None and k == "launch_url" and row["app"]) or
                             (row[k] is not None and "." not in _host(row[k]))]
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="include services the config disables")
    a = ap.parse_args(argv)
    json.dump(plan(include_disabled=a.all), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
