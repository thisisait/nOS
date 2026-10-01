"""Effect probes: what each plugin says "wired" means, checked on the live estate.

A plugin's `e2e.probes` sit beside the wiring they verify (plugin.yml) and are
rendered by tools/e2e-plan.py against the resolved config; only enabled
services and probes whose `when` renders true run. Kinds:
  http — method, url, auth (anon | tester | bearer / header / basic from a
         named secret | keap_proxy), expect {status, contains, json paths,
         contains_tester}; `sso_start` makes a tester walk the app's OWN
         "Sign in with Authentik" first, so the app half of SSO is exercised
  tcp  — host, port, expect {banner_prefix}
Secrets are read by name (lib/estate_secrets) and never printed.
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest
import requests

from conftest import load_plan
from lib.estate_secrets import secret
from lib.sso_walk import REACHED, walk

REPO = Path(__file__).resolve().parents[3]
TRUE = ("1", "true", "yes", "y", "on")

try:
    PLAN = load_plan()
except Exception:  # noqa: BLE001
    PLAN = []
PROBES = [(s, p) for s in PLAN for p in (s.get("probes") or [])
          if str(p.get("when", "true")).strip().lower() in TRUE]


def _need(key: str) -> str:
    v = secret(key)
    if not v:
        pytest.fail(f"probe needs secret {key!r}, which is neither persisted nor derivable")
    return v


def _headers(auth) -> tuple[dict, tuple | None]:
    if not isinstance(auth, dict):
        return {}, None
    h, basic = {}, None
    if "bearer" in auth:
        h["Authorization"] = f"Bearer {_need(auth['bearer'])}"
    for name, key in (auth.get("headers") or {}).items():
        h[name] = _need(key)
    if auth.get("keap_proxy"):
        sys.path.insert(0, str(REPO / "tools"))
        from keap_api import proxy_header
        h.update(proxy_header())
    if "basic" in auth:
        basic = (auth["basic"]["user"], _need(auth["basic"]["secret"]))
    return h, basic


def _dig(data, path: str):
    for part in [p for p in str(path).split(".") if p]:
        if isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        elif isinstance(data, dict):
            data = data.get(part)
        else:
            return None
    return data


def _check_json(data, exp: dict) -> list[str]:
    bad = []
    for path, want in (exp.get("json_equals") or {}).items():
        if _dig(data, path) != want:
            bad.append(f"{path} = {_dig(data, path)!r}, want {want!r}")
    for path, n in (exp.get("json_min_len") or {}).items():
        got = _dig(data, path)
        if not isinstance(got, list) or len(got) < int(n):
            bad.append(f"len({path}) = {len(got) if isinstance(got, list) else got!r}, want >= {n}")
    for path, spec in (exp.get("json_any") or {}).items():
        items = _dig(data, path) or []
        if not any(str(_dig(i, spec["field"])).find(str(spec["contains"])) >= 0 for i in items):
            bad.append(f"no {path}[].{spec['field']} contains {spec['contains']!r}")
    for path, spec in (exp.get("json_all") or {}).items():
        off = [_dig(i, spec.get("name", "id")) for i in (_dig(data, path) or [])
               if _dig(i, spec["field"]) not in spec["in"]]
        if off:
            bad.append(f"{path}[] with {spec['field']} not in {spec['in']}: {off}")
    return bad


@pytest.mark.parametrize("svc,probe", PROBES, ids=[f"{s['slug']}:{p['name']}" for s, p in PROBES])
def test_probe(svc, probe, testers, verify_tls, auth_host):
    exp = probe.get("expect") or {}
    if probe.get("kind", "http") == "tcp":
        with socket.create_connection((probe["host"], int(probe["port"])), timeout=10) as sock:
            banner = sock.recv(256).decode(errors="replace")
        assert banner.startswith(str(exp.get("banner_prefix", ""))), f"{svc['slug']}: banner {banner[:60]!r}"
        return
    auth = probe.get("auth", "anon")
    tier = int(probe.get("tier") or svc["tier"] or 4)
    sess = testers(tier) if auth == "tester" else requests.Session()
    if probe.get("sso_start"):
        start = svc["first_login"] if probe["sso_start"] is True else probe["sso_start"]
        w = walk(sess, start, auth_host, verify=verify_tls)
        assert w.outcome == REACHED, (f"{svc['slug']} · {probe['name']}: SSO start {w.outcome} at {w.url} "
                                      f"({w.status})\n  " + "\n  ".join(w.trail))
    headers, basic = _headers(auth)
    headers.update(probe.get("send_headers") or {})
    r = sess.request(probe.get("method", "GET"), probe["url"], headers=headers, auth=basic,
                     json=probe.get("body"), timeout=30, verify=verify_tls,
                     allow_redirects=bool(probe.get("follow", False)))
    problems = []
    if r.status_code not in [int(s) for s in exp.get("status", [200])]:
        problems.append(f"status {r.status_code}")
    if exp.get("contains") and str(exp["contains"]) not in r.text:
        problems.append(f"body lacks {exp['contains']!r}")
    if exp.get("contains_tester"):
        who = getattr(testers, "username", lambda t: None)(tier)
        if not who or who not in r.text:
            problems.append(f"the app does not know the tier-{tier} tester {who!r}")
    if any(k.startswith("json_") for k in exp):
        try:
            problems += _check_json(r.json(), exp)
        except ValueError:
            problems.append("body is not JSON")
    assert not problems, f"{svc['slug']} · {probe['name']}: " + "; ".join(problems) + f" — {r.text[:160]!r}"
