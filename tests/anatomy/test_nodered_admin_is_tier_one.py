"""Node-RED gives full admin ('*') to tier 1 only; a login without groups is refused.

RBAC audit 2026-10-21: settings.js.j2 granted permissions '*' to every
authenticated identity (verify() and users() both), so any Authentik user
with RBAC tier-2 access to Node-RED could edit flows and credential nodes. This renders
the template and runs its adminAuth in node, so the gate reads behaviour.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import jinja2
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

SETTINGS = REPO / "roles/pazny.nodered/templates/settings.js.j2"
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node is how settings.js's adminAuth is executed")

_DRIVER = r"""
const Module = require('module');
const load = Module._load;
Module._load = (r, ...a) => r === 'passport-openidconnect' ? { Strategy: function () {} } : load(r, ...a);
const s = require(process.argv[2]);
const verify = s.adminAuth.strategy.options.verify;
const out = {};
const cases = JSON.parse(process.argv[3]);
(async () => {
  for (const [name, groups] of Object.entries(cases)) {
    const json = groups === null ? {} : { groups };
    const vr = await new Promise(res => verify('iss', { username: name, _json: json }, (e, u) => res(u || null)));
    const u = await s.adminAuth.users(name);
    out[name] = { verified: !!vr, permissions: u ? u.permissions : null };
  }
  out.never_seen = await s.adminAuth.users('never_seen');
  console.log(JSON.stringify(out));
})();
"""


def _tier1() -> list[str]:
    return next(t["groups"] for t in ni.default_config()["authentik_rbac_tiers"] if t["tier"] == 1)


def _render(tmp: Path) -> Path:
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    env.filters["bool"] = lambda v: str(v).lower() in {"1", "true", "yes"}
    out = tmp / "settings.js"
    out.write_text(env.from_string(SETTINGS.read_text(encoding="utf-8")).render(
        install_authentik=True, nodered_native_oidc_enabled=True,
        authentik_rbac_tiers=ni.default_config()["authentik_rbac_tiers"], authentik_domain="auth.test", nodered_domain="nodered.test",
    ), encoding="utf-8")
    return out


@needs_node
def test_only_tier_one_is_admin(tmp_path: Path) -> None:
    tier1 = _tier1()
    assert len(tier1) >= 2, "tier 1 holds more than one group; the gate must see every one"
    cases = {f"t1_{g}": [g] for g in tier1}
    cases |= {"manager": ["nos-managers"], "user": ["nos-users", "nos-guests"], "nogroups": None}
    driver = tmp_path / "driver.js"
    driver.write_text(_DRIVER, encoding="utf-8")
    r = subprocess.run(["node", str(driver), str(_render(tmp_path)), json.dumps(cases)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    for g in tier1:
        assert got[f"t1_{g}"]["permissions"] == "*", f"tier-1 group {g} is not admin: {got[f't1_{g}']}"
    for who in ("manager", "user"):
        assert got[who]["permissions"] not in ("*", ["*"]), f"{who} is admin in Node-RED: {got[who]}"
    assert got["nogroups"] == {"verified": False, "permissions": None}, f"a login with no groups claim got in: {got['nogroups']}"
    assert got["never_seen"] is None, f"users() admits a name that never signed in: {got['never_seen']}"
