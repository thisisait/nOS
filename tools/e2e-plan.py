#!/usr/bin/env python3
"""What the estate promises a user, rendered from the manifests — the E2E plan.

One source of truth: each plugin's `authentik:` block already says how a person
reaches the service (mode, tier, client, redirect, launch URL, enabled), and an
optional `e2e:` block says what "wired" means after start. This renders both
against the SAME resolved config nos-smoke probes (tools/nos-smoke.py
load_vars: defaults → config.yml → ~/.nos/state.yml → domain helpers), so a
journey can never be written for a service the configuration does not run.
Enablement — services AND manifest apps — is what the last converge ran
(state.yml, -e profiles included); stderr names the source it used.

  tools/e2e-plan.py                 # JSON plan of the enabled services
  tools/e2e-plan.py --all           # include disabled ones (enabled: false)
  tools/e2e-plan.py --journeys      # one argv line per declared journey; prints, never runs

A plugin's `e2e.journeys` names specs under tests/e2e/journeys (row iris-approvals-e2e-plan).
A journey writes to the live estate, so running one stays the operator's act.
"""
from __future__ import annotations

import argparse
import getpass
import importlib.util
import json
import re
import shlex
import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[1]
PLUGINS = REPO / "files/anatomy/plugins"
sys.path.insert(0, str(REPO / "tools"))
from nos_identity import SYNTHETIC_FLAG, installed_apps, plugin_installed, ran, synthetic_identities  # noqa: E402
MODES = ("native_oidc", "forward_auth", "header_oidc")
JOURNEYS = REPO / "tests/e2e/journeys"
JOURNEY_ENV = {"FACE_E2E"}      # flags only: tokens stay with the conftest / run-playwright.sh
JOURNEY_SPEC = {"playwright": re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.spec\.ts"), "pytest": re.compile(r"test_[A-Za-z0-9_]+\.py")}
RUNNER = {"playwright": ["tools/run-playwright.sh", "journeys/{spec}"],
          "pytest": ["python3", "-m", "pytest", "tests/e2e/journeys/{spec}", "-q"]}

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


def _journeys(raw) -> tuple[list[dict], list[str]]:
    """(accepted, refused) from a plugin's e2e.journeys. Plugin data becomes argv, so a spec is a
    bare file name that exists under tests/e2e/journeys; anything else is refused by name, never
    dropped. Literal data: not Jinja-rendered."""
    ok, refused = [], []
    for entry in raw if isinstance(raw, list) else [raw]:
        j = entry if isinstance(entry, dict) else {}
        spec, runner, env = j.get("spec"), j.get("runner"), j.get("env") or {}
        pat = JOURNEY_SPEC.get(runner) if isinstance(runner, str) else None
        if (isinstance(spec, str) and ".." not in spec and pat and pat.fullmatch(spec) and (JOURNEYS / spec).is_file()
                and isinstance(env, dict) and all(k in JOURNEY_ENV and v in ("0", "1") for k, v in env.items())):
            ok.append({"name": str(j.get("name") or spec), "spec": spec, "runner": runner, "env": dict(env)})
        else:
            label = "".join(c if c.isprintable() else " " for c in str(spec or j.get("name") or entry))
            refused.append(f"journey:{label}"[:80])
    return ok, refused


def journey_argv(j: dict) -> str:
    argv = [a.format(spec=j["spec"]) for a in RUNNER[j["runner"]]]
    env = [f"{k}={v}" for k, v in sorted(j["env"].items())]
    return shlex.join(["env", *env, *argv] if env else argv)


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
    """nos_identities as this config resolves them, plus the synthetic ones
    (kind: synthetic) while their switch is on — off, they have no account."""
    vars_, env = _resolved(vars_)
    ids = [i for i in vars_.get("nos_identities") or [] if isinstance(i, dict)]
    if _truthy(_render(env, vars_.get(SYNTHETIC_FLAG, False))):
        ids += synthetic_identities(vars_)
    return [_render(env, i) for i in ids]


def plan(vars_: dict | None = None, include_disabled: bool = False) -> list[dict]:
    vars_, env = _resolved(vars_)
    edge, domains = _edge_modes(), _manifest_domains()
    rows = []
    docs = {p: yaml.safe_load(p.read_text(encoding="utf-8")) or {} for p in sorted(PLUGINS.glob("*/plugin.yml"))}
    plugins = {d.get("name"): d for d in docs.values()}
    for path, doc in docs.items():      # discovery, gitleaks carry no -base
        ak = doc.get("authentik") or {}
        e2e = doc.get("e2e") or {}
        if not ak and not e2e:
            continue
        # client_secret stays unrendered: a plan is not a secrets carrier.
        ak = {k: v for k, v in ak.items() if k != "client_secret"}
        r = _render(env, ak)
        enabled = _truthy(r.get("enabled", _render(env, e2e.get("enabled", "false"))))
        # The Pulse catalog's rule (requires.feature_flag + peers): a plugin it drops has no wiring to probe.
        enabled = enabled and plugin_installed(doc.get("name"), plugins, vars_)
        if not enabled and not include_disabled:
            continue
        redirects = r.get("redirect_uris") or []
        key = path.parent.name.removesuffix("-base").replace("-", "_")
        launch = r.get("launch_url")
        journeys, refused = _journeys(e2e.get("journeys") or [])
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
            # An app only identities of this realm can enter (jupyterhub: unix).
            "first_login_realm": r.get("first_login_realm"),
            "edge": edge.get(key, "proxy"),
            "enabled": enabled,
            "probes": _render(env, e2e.get("probes") or []),
            "isolation": _render(env, e2e.get("isolation") or []),
            "journeys": journeys,
            "refused": refused,
            "app": bool(ak),     # e2e-only plugins (backup, alert-relay) have no URL to open
        })
    # Manifest apps (apps/*.yml) carry their own authentik: block and were
    # invisible to a plugin-only walk: documenso, twofauth, roundcube.
    # Same rendering, same edge rule.
    by_slug = {r["slug"]: r for r in rows}
    apps_on = set(installed_apps(vars_))
    for path in sorted((REPO / "apps").glob("*.yml")):
        if path.name.startswith("_"):
            continue
        ak = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("authentik") or {}
        if not ak:
            continue
        r = _render(env, {k: v for k, v in ak.items() if k != "client_secret"})
        slug = r.get("slug") or path.stem
        enabled = path.stem in apps_on
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
                     "edge": "proxy", "enabled": enabled, "probes": [], "isolation": [], "journeys": [],
                     "refused": [], "app": True})
    for row in rows:
        row["unresolved"] = [k for k in ("launch_url", "redirect_uri")
                             if (row[k] is None and k == "launch_url" and row["app"]) or
                             (row[k] is not None and "." not in _host(row[k]))] + row.pop("refused")
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="include services the config disables")
    ap.add_argument("--journeys", action="store_true", help="print each journey's argv; runs nothing")
    a = ap.parse_args(argv)
    # What is enabled comes from what the last converge RAN (state.yml, -e
    # included); the layers only when no run is recorded. Say which, on stderr.
    run = ran()
    print(f"enablement: {run.provenance()}", file=sys.stderr)
    if run.source == "state.yml" and run.apps() is None:
        print("apps: layers (this state.yml predates the apps record; the next converge writes it)",
              file=sys.stderr)
    rows = plan(include_disabled=a.all)
    if a.journeys:      # exit 0 either way: a reader-shaped renderer; unresolved is the channel
        for r in rows:
            for j in r["journeys"] if r["enabled"] else ():
                print(journey_argv(j))
            for u in (u for u in r["unresolved"] if u.startswith("journey:")):
                print(f"# unresolved {r['slug']}: {u}", file=sys.stderr)
        return 0
    json.dump(rows, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
