"""The E2E plan is rendered from the manifests, and the walk reads Authentik right.

tools/e2e-plan.py must: cover every plugin authentik: block and every
apps/*.yml one, resolve each enabled service to a URL, carry the Traefik edge
mode (proxy/none/oidc) next to the plugin's claim, and report an unresolvable
URL instead of dropping the row. tests/e2e/lib/sso_walk.py is run against a
scripted session: reach, Authentik's "Permission denied" page, a code on the
redirect host, and a flow interface resolved through the executor.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("e2e_plan", REPO / "tools/e2e-plan.py")
plan_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan_mod)
sys.path.insert(0, str(REPO / "tests/e2e"))
from lib import sso_walk  # noqa: E402

VARS = {**plan_mod.smoke.merge_config(REPO / "default.config.yml"),
        "tenant_domain": "example.test", "_host_alias_seg": "", "apps_runner_enabled": True,
        "install_paperclip": True, "install_ntfy": True, "install_gitea": True}


def _plan():
    return plan_mod.plan(VARS, include_disabled=True)


def test_every_authentik_block_becomes_a_row():
    rows = {r["slug"] for r in _plan()}
    for p in sorted((REPO / "files/anatomy/plugins").glob("*-base/plugin.yml")):
        ak = (yaml.safe_load(p.read_text()) or {}).get("authentik") or {}
        if ak.get("slug"):
            assert ak["slug"] in rows, p
    for a in (REPO / "apps").glob("[!_]*.yml"):
        ak = (yaml.safe_load(a.read_text()) or {}).get("authentik") or {}
        if ak.get("slug"):
            assert ak["slug"] in rows, a


def test_enabled_rows_resolve_and_carry_the_edge():
    rows = {r["slug"]: r for r in _plan()}
    assert rows["paperclip"]["launch_url"] == "https://paperclip.example.test"
    assert rows["paperclip"]["edge"] == "proxy" and rows["ntfy"]["edge"] == "none"
    assert rows["gitea"]["mode"] == "native_oidc" and rows["gitea"]["redirect_uri"].startswith("https://git.")
    assert "qdrant" in rows and rows["qdrant"]["launch_url"].startswith("https://qdrant.apps.")
    assert not any("{{" in str(r["launch_url"]) for r in rows.values())


def test_an_unresolvable_url_is_reported_not_dropped():
    v = dict(VARS)
    v["paperclip_domain"] = ""
    rows = {r["slug"]: r for r in plan_mod.plan(v, include_disabled=True)}
    assert "launch_url" in rows["paperclip"]["unresolved"], rows["paperclip"]


class _Resp:
    def __init__(self, status=200, location=None, text="", json=None):
        self.status_code, self.text, self._json = status, text, json
        self.headers = {"location": location} if location else {}
        if json is not None:
            self.headers["content-type"] = "application/json"
        self.is_redirect = location is not None

    def json(self):
        return self._json


class _Sess:
    def __init__(self, routes):
        self.routes, self.headers, self.seen = routes, {}, []

    def get(self, url, **kw):
        self.seen.append((url, kw.get("headers", {}).get("Accept")))
        for prefix, resp in self.routes:
            if url.startswith(prefix):
                return resp
        raise AssertionError(url)

    post = get


AUTH = "auth.example.test"


def test_the_walk_reaches_a_gated_service_and_asks_for_html():
    s = _Sess([("https://app.example.test/x", _Resp(200, text="app")),
               ("https://app.example.test", _Resp(302, "https://auth.example.test/application/o/authorize/?c=1")),
               ("https://auth.example.test/application/o/authorize/", _Resp(302, "https://app.example.test/x"))])
    w = sso_walk.walk(s, "https://app.example.test", AUTH)
    assert w.outcome == sso_walk.REACHED and w.url.endswith("/x")
    assert all(a and a.startswith("text/html") for _, a in s.seen), "a hop went out without the HTML Accept"


def test_the_permission_denied_page_is_a_denial():
    s = _Sess([("https://auth.example.test/application/o/authorize/",
                _Resp(200, text="<title>\nPermission denied - authentik\n</title>"))])
    w = sso_walk.walk(s, "https://auth.example.test/application/o/authorize/?c=1", AUTH)
    assert w.outcome == sso_walk.DENIED


def test_a_flow_interface_goes_through_the_executor_to_a_code():
    s = _Sess([("https://auth.example.test/api/v3/flows/executor/consent/",
                _Resp(200, json={"component": "xak-flow-redirect", "to": "https://app.example.test/cb?code=abc"})),
               ("https://auth.example.test/if/flow/consent/", _Resp(200, text="js app"))])
    w = sso_walk.walk(s, "https://auth.example.test/if/flow/consent/?next=x", AUTH,
                      stop_at_code_for="app.example.test")
    assert w.outcome == sso_walk.CODE


def test_every_declared_probe_renders_to_a_runnable_shape():
    """Each plugin e2e probe, rendered against the defaults, has a known kind,
    a URL (or host/port) with no Jinja left, and an auth the runner knows."""
    probes = [(r["slug"], p) for r in _plan() for p in r["probes"]]
    assert len(probes) >= 20, len(probes)
    for slug, p in probes:
        kind = p.get("kind", "http")
        assert kind in ("http", "tcp"), (slug, p)
        text = str(p.get("url") or "") + str(p.get("host", "")) + str(p.get("port", ""))
        assert "{{" not in text and text, (slug, p["name"], text)
        if kind == "http":
            assert "://" in p["url"] and "." in p["url"].split("://", 1)[1].split("/")[0], (slug, p["url"])
        auth = p.get("auth", "anon")
        assert auth in ("anon", "tester") or (isinstance(auth, dict) and set(auth) <= {
            "bearer", "headers", "basic", "keap_proxy"}), (slug, auth)
        if p.get("sso_start"):
            assert auth == "tester" and "://" in p["sso_start"], (slug, p["name"])
