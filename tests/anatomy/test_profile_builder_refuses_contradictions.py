"""The profile builder cannot hand anyone a config the estate contradicts.

Rules are derived (tools/profile-builder/rules.py) and carried by the page as data.
The sweep runs every profile combination × mail × test users × one person (× a
public domain), and from each every install_* toggle, through the page's own JS;
each downloadable config is judged by the playbook's REAL expressions, in Jinja.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("pb", REPO / "tools/profile-builder-build.py")
pb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pb)
rules = pb.rules
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node is how the page's own logic is executed")
SMALL = {"picks": [{"service-set": "dev-minimal"}, {}], "domains": [None]}


@pytest.fixture(scope="module")
def data() -> dict:
    return pb.build()


def _by(data, cls):
    return [r for r in data["rules"] if r["cls"] == cls]


def test_the_rules_come_from_the_sources(data):
    auto = {(r["consumer"]["flag"], r["upstream"][0]) for r in _by(data, "auto")}
    assert ("install_outline", "install_postgresql") in auto and ("install_onlyoffice", "redis_docker") in auto
    silent = {(json.dumps(r["consumer"], sort_keys=True), tuple(r["upstream"])) for r in _by(data, "silent")}
    for c, u in [({"flag": "install_woodpecker"}, ("install_gitea",)), ({"flag": "install_nextcloud"}, ("install_onlyoffice",)),
                 ({"flag": "install_gitea"}, ("install_authentik",)), ({"people": True}, ("install_authentik",)),
                 ({"field": "nos_test_users_enabled"}, ("install_authentik",)),
                 ({"knob": "wing_audit_chain_enabled", "profile": "gov-local"}, ("install_bone", "install_wing")),
                 ({"knob": "backup_encryption_enabled", "profile": "gov-local"}, ("install_backup",))]:
        assert (json.dumps(c, sort_keys=True), u) in silent, f"lost a derived rule: {c} needs {u}"
    refused = {name: r for r in _by(data, "refused") for name in re.findall(r"(?:^| \+ )[^:]+: ([^+]+?)(?= \+ |$)", r["source"])}
    for name in ("[Preflight] Refuse if no edge proxy is enabled", "[Preflight] Refuse a forward-auth gate with no Authentik behind it",
                 "[Preflight] Refuse if BOTH install_nginx and install_traefik are true",
                 "[ACME] Refuse to run without a Cloudflare API token", "[pazny.smtp_stalwart] Refuse on local TLD (production-only role)"):
        assert name in refused, f"the extractor no longer finds `{name}`: {list(refused)}"
    assert any("erpnext" in k for k in refused), "ERPNext's hard guard is a refusal the page can reach"
    gate = refused["[Preflight] Refuse a forward-auth gate with no Authentik behind it"]
    assert "install_wing" in gate["any"] and "install_observability" not in gate["any"], \
        "the gated set is the rendered services.yml.j2 (grafana is native OIDC, not gated)"
    assert data["local_suffixes"] == [".local", ".lan", ".test", ".localhost"]
    assert data["derived"] == {"tenant_domain_is_local": "local", "install_acme": "public"}


@needs_node
def test_the_sweep_lets_no_contradiction_through(data):
    r = rules.sweep(data)
    print(f"\nsweep: {r['states']} states, {r['blocked']} blocked, {r['configs']} configs judged, {r['seconds']}")
    assert r["states"] > 60_000 and r["configs"] > 5_000, "the sweep stopped covering what it claims"
    assert not r["leaks"], "the page lets these through:\n" + "\n".join(f"{w}\n  {s}" for w, s in r["leaks"].items())
    assert r["seconds"]["total"] < 60, f"the sweep is too slow for CI: {r['seconds']}"


def _alone(data, logic=None) -> dict:
    js = (logic or rules.logic_js()) + f"\nconst DATA={json.dumps(data)};\n" + r"""
      const s = picks => ({fields: {global_password_prefix: "FAKEsweep12345678", restic_repo: "/Volumes/B/r"},
                           picks, mail: null, manual: {}, people: []});
      const out = {"": problems(DATA, s({})).map(p => p.msg)};
      for (const p of DATA.profiles.filter(p => !p.step)) out[p.id] = problems(DATA, s({[p.axis]: p.id})).map(p => p.msg);
      console.log(JSON.stringify(out));"""
    return json.loads(subprocess.run(["node", "-"], input=js, capture_output=True, text=True, check=True).stdout)


@needs_node
def test_no_profile_the_page_offers_is_itself_a_contradiction(data):
    assert {k: v for k, v in _alone(data).items() if v} == {}, "a profile picked on its own is refused"


@needs_node
def test_the_gate_goes_red_when_a_rule_is_dropped(data):
    no_silent = copy.deepcopy(data)
    no_silent["rules"] = [r for r in data["rules"] if r["cls"] != "silent"]
    leaks = rules.sweep(data, SMALL, page_data=no_silent)["leaks"]
    assert any("woodpecker-base" in w for w in leaks), f"dropping the depends_on rules went unnoticed: {list(leaks)[:3]}"
    no_refused = copy.deepcopy(data)
    no_refused["rules"] = [r for r in data["rules"] if r["cls"] != "refused"]
    leaks = rules.sweep(data, {**SMALL, "picks": [{}]}, page_data=no_refused)["leaks"]
    assert any("edge proxy" in w for w in leaks) and any("smtp_stalwart" in w for w in leaks), list(leaks)


@needs_node
def test_the_gate_goes_red_on_a_contradictory_profile_or_a_page_without_its_checks(data):
    broken = copy.deepcopy(data)
    broken["profiles"].append({"id": "broken", "axis": "use-case", "plain": "x", "step": None,
                               "flags": {"install_erpnext": True}, "knobs": {}})
    assert _alone(broken)["broken"], "a profile that turns on a refused service must be caught"
    soft = rules.logic_js().replace("P.push(...refusedProblems(data, s, st), ...unmetProblems(data, st));", "")
    assert soft != rules.logic_js()
    leaks = rules.sweep(data, SMALL, logic=soft)["leaks"]
    assert leaks, "a page without its refusals still passed the sweep"


def test_the_publication_runs_the_sweep_first():
    wf = yaml.safe_load((REPO / ".github/workflows/pages.yml").read_text())
    steps = [s.get("name", "") + " :: " + str(s.get("run", "")) for s in wf["jobs"]["build"]["steps"]]
    sweep = next(i for i, s in enumerate(steps) if "profile-builder-build.py --sweep" in s)
    render = next(i for i, s in enumerate(steps) if s.startswith("Render the profile builder"))
    assert sweep < render, "a contradictory builder could be published before the sweep runs"
    assert re.search(r'shutil\.which\("node"\)\s*\n\s*if not node:\s*\n\s*raise SystemExit', (REPO / "tools/profile-builder/rules.py").read_text()), \
        "without node the sweep must fail the publish, never skip it"
