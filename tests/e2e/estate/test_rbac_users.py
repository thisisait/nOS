"""RBAC and per-user storage, for the declared test users.

Users are the synthetic identities (alice/bob/carol/dave, kind: synthetic in
profiles/test-users.yml); services are the same plan rows the config
journeys walk. Nothing is listed here:
  * every test user reaches each gated / native-OIDC service at or above its
    tier and is refused by Authentik below it;
  * a plugin's `e2e.isolation` probe: user A writes a private marker and reads
    it back (the control), a peer B at the same tier asks for it and must not
    get it.
With the toggle off every test skips, naming it.
"""
from __future__ import annotations

import uuid
from urllib.parse import urlparse

import pytest

from conftest import load_identities, load_plan
from lib.sso_walk import CODE, DENIED, REACHED, walk
from test_config_journeys import GATED, NATIVE, _authorize_url

try:
    USERS = [i for i in load_identities() if i.get("kind") == "synthetic"]
    _WHY = ("no test user is enabled — set nos_test_users_enabled: true "
            "(nos -e @profiles/test-users.yml) and converge")
except Exception as exc:  # noqa: BLE001
    USERS, _WHY = [], f"nos_identities did not resolve: {exc}"
try:
    PLAN = load_plan()
except Exception:  # noqa: BLE001
    PLAN = []
pytestmark = pytest.mark.skipif(not USERS, reason=_WHY)

MATRIX = [(u, s) for u in USERS for s in GATED + NATIVE]
ISOLATION = [(s, p) for s in PLAN for p in (s.get("isolation") or [])]


@pytest.fixture(scope="session")
def users(auth_host, verify_tls):
    """identity → Authentik-logged-in requests.Session, one login per user."""
    from lib.authentik_login import login_session
    from lib.estate_secrets import identity_password

    sessions: dict[str, object] = {}

    def get(user: dict):
        if user["name"] not in sessions:
            pw = identity_password(user["password_var"])
            if not pw:
                pytest.fail(f"{user['name']}: {user['password_var']} is neither persisted nor derivable")
            sessions[user["name"]] = login_session(user["name"], pw, authentik_domain=auth_host,
                                                   ignore_tls=not verify_tls)
        return sessions[user["name"]]
    return get


def test_the_test_users_cover_every_tier_below_admin():
    tiers = {u["tier"] for u in USERS}
    assert {2, 3, 4} <= tiers, f"declared test users cover tiers {sorted(tiers)}"


@pytest.mark.parametrize("user,svc", MATRIX, ids=[f"{u['name']}-t{u['tier']}:{s['slug']}-t{s['tier']}" for u, s in MATRIX])
def test_a_user_reaches_its_tier_and_is_refused_above_it(user, svc, users, auth_host, verify_tls):
    allowed = user["tier"] <= svc["tier"]
    if svc["mode"] == "native_oidc":
        w = walk(users(user), _authorize_url(auth_host, svc), auth_host, verify=verify_tls,
                 stop_at_code_for=urlparse(svc["redirect_uri"]).netloc)
        ok = w.outcome == (CODE if allowed else DENIED)
    else:
        w = walk(users(user), svc["launch_url"], auth_host, verify=verify_tls)
        ok = (w.outcome == REACHED and urlparse(w.url).netloc == urlparse(svc["launch_url"]).netloc
              if allowed else w.outcome == DENIED)
    assert ok, (f"{user['name']} (tier {user['tier']}) on {svc['slug']} (tier {svc['tier']}): expected "
                f"{'access' if allowed else 'refusal'}, got {w.outcome} at {w.url}\n  " + "\n  ".join(w.trail))


def _dig(data, path: str):
    for part in [p for p in str(path).split(".") if p]:
        data = data[int(part)] if isinstance(data, list) else (data or {}).get(part)
    return data


def _fill(value, tokens: dict):
    if isinstance(value, str):
        for k, v in tokens.items():
            value = value.replace(f"@{k}@", str(v))
        return value
    if isinstance(value, dict):
        return {k: _fill(v, tokens) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, tokens) for v in value]
    return value


def _call(sess, step: dict, tokens: dict, headers: dict, verify: bool):
    body = _fill(step.get("body"), tokens)
    return sess.request(step.get("method", "GET"), _fill(step["url"], tokens), headers=headers,
                        json=body if isinstance(body, (dict, list)) else None,
                        data=body if isinstance(body, str) else None,
                        timeout=30, verify=verify, allow_redirects=False)


@pytest.mark.parametrize("svc,probe", ISOLATION, ids=[f"{s['slug']}:{p['name']}" for s, p in ISOLATION])
def test_a_users_private_data_stays_private(svc, probe, users, auth_host, verify_tls):
    peers = sorted((u for u in USERS if u["tier"] <= (svc["tier"] or 4)), key=lambda u: (-u["tier"], u["name"]))
    if len(peers) < 2:
        pytest.skip(f"{svc['slug']}: needs two test users at tier <= {svc['tier']}, have {[u['name'] for u in peers]}")
    (a, sa), (b, sb) = [(u, users(u)) for u in peers[:2]]
    heads = {}
    for u, s in ((a, sa), (b, sb)):
        if probe.get("sso_start"):
            start = svc["first_login"] if probe["sso_start"] is True else probe["sso_start"]
            w = walk(s, start, auth_host, verify=verify_tls)
            assert w.outcome == REACHED, f"{u['name']} → {svc['slug']}: SSO start {w.outcome} at {w.url}"
        heads[u["name"]] = dict(probe.get("send_headers") or {})
        if probe.get("csrf"):
            c = probe["csrf"]
            heads[u["name"]][c["header"]] = (s.cookies.get(c["cookie"]) if "cookie" in c else  # Outline
                                             _dig(s.get(c["url"], headers=heads[u["name"]], timeout=20,
                                                        verify=verify_tls).json(), c["path"]))
    # marker names the object (it may echo in a 404); secret is its CONTENT,
    # the only thing whose presence in a peer's answer is a leak.
    tokens = {"marker": f"nos-e2e-{uuid.uuid4().hex[:12]}", "secret": f"nos-e2e-secret-{uuid.uuid4().hex}"}
    if probe.get("owner"):
        tokens["owner"] = _dig(sa.get(probe["owner"]["url"], headers=heads[a["name"]], timeout=20,
                                      verify=verify_tls).json(), probe["owner"]["path"])
    w = _call(sa, probe["write"], tokens, heads[a["name"]], verify_tls)
    assert w.status_code in probe["write"]["status"], f"{a['name']} could not write: {w.status_code} {w.text[:160]!r}"
    if probe.get("id_path"):
        tokens["id"] = _dig(w.json(), probe["id_path"])
    try:
        own = _call(sa, probe["read"], tokens, heads[a["name"]], verify_tls)
        assert own.status_code in probe["read"]["status"] and tokens["secret"] in own.text, (
            f"control failed: {a['name']} cannot read back its own marker ({own.status_code})")
        other = _call(sb, probe["read"], tokens, heads[b["name"]], verify_tls)
        assert other.status_code in probe["peer"]["status"] and tokens["secret"] not in other.text, (
            f"{b['name']} got {a['name']}'s private data from {svc['slug']}: {other.status_code} {other.text[:160]!r}")
    finally:
        if probe.get("cleanup"):
            _call(sa, probe["cleanup"], tokens, heads[a["name"]], verify_tls)
