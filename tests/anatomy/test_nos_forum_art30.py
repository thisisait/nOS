"""nos-forum Art-30: the register row is the deploy gate, and it is honest.

Shape copied from test_device_gateway_art30.py. Pins: a complete gdpr block in
nos-forum-base; the converge refuses install_nos_forum without it (and without
SpacetimeDB + Authentik); DSAR maps and the register carry the service; the
retention claim matches what exists (v0.1 has no retention job, so the note must
say so — a declared job flips the requirement); the flag ships off.
Policy: docs/compliance/nos-forum.md.
"""
from __future__ import annotations

import pathlib

import yaml

from test_device_gateway_art30 import gdpr_block_is_complete  # type: ignore
from module_utils.nos_app_parser import REQUIRED_GDPR  # type: ignore

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGIN = REPO / "files/anatomy/plugins/nos-forum-base/plugin.yml"
MAIN = REPO / "main.yml"
DOC = REPO / "docs/compliance/nos-forum.md"
ERASURE = REPO / "state/gdpr-erasure-map.yml"
EXPORT = REPO / "state/gdpr-export-map.yml"
REGISTER = REPO / "state/dpa-register.md"
JOB = "nos-forum-retention"


def _plugin() -> dict:
    return yaml.safe_load(PLUGIN.read_text(encoding="utf-8")) or {}


def retention_is_honest(plugin: dict) -> tuple[bool, str]:
    """A declared job and the note's claim must agree, both ways."""
    jobs = ((plugin.get("pulse") or {}).get("jobs")) or []
    has_job = any(j.get("name") == JOB for j in jobs)
    note = str((plugin.get("gdpr") or {}).get("notes", ""))
    if "retention_enforced: true" in note:
        return has_job, f"note claims retention is enforced but no {JOB} job is declared"
    return (not has_job and "retention_enforced: false" in note,
            "the note must say retention_enforced: false while no job exists (or declare the job and say true)")


def _tasks() -> list[dict]:
    return yaml.safe_load(MAIN.read_text(encoding="utf-8"))[0]["tasks"]


def test_plugin_carries_a_complete_art30_block():
    p = _plugin()
    assert gdpr_block_is_complete(p.get("gdpr") or {}) == []
    assert (p.get("requires") or {}).get("feature_flag") == "install_nos_forum"
    assert "end_users" in p["gdpr"]["data_subjects"]
    assert p["authentik"]["mode"] == "native_oidc"


def test_the_gate_is_red_on_a_broken_block():
    assert gdpr_block_is_complete({**_plugin()["gdpr"], "retention_days": 0})
    assert gdpr_block_is_complete({k: v for k, v in _plugin()["gdpr"].items() if k != "processors"})


def test_converge_refuses_the_flag_without_the_block_or_its_dependencies():
    tasks = _tasks()
    names = [t.get("name", "") for t in tasks]
    gate = names.index("[Art-30] Refuse nos-forum without a complete gdpr block")
    deps = [names.index(f"[nos-forum] Refuse install_nos_forum without {x}") for x in ("SpacetimeDB", "Authentik")]
    stacks = next(i for i, t in enumerate(tasks) if t.get("import_tasks") == "tasks/stacks/stack-up.yml")
    assert gate < stacks and max(deps) < stacks, "the refusals must run before the iiab render"
    that = " ".join(tasks[gate]["ansible.builtin.assert"]["that"])
    for key in REQUIRED_GDPR:
        assert key in that, f"assert does not check gdpr.{key}"
    assert "nos-forum-base/plugin.yml" in tasks[gate]["vars"]["_forum_gdpr"]
    whens = " ".join(" ".join(tasks[i]["when"]) for i in deps)
    assert "not (install_spacetimedb" in whens and "not (install_authentik" in whens


def test_retention_claim_matches_what_exists():
    ok, why = retention_is_honest(_plugin())
    assert ok, why
    # red: the note claims enforcement, no job exists
    assert not retention_is_honest({"gdpr": {"notes": "retention_enforced: true"}})[0]
    # red: a job appears but the note still says false
    assert not retention_is_honest({"pulse": {"jobs": [{"name": JOB}]}, "gdpr": {"notes": "retention_enforced: false"}})[0]


def test_dsar_maps_and_register_carry_the_service():
    for path in (ERASURE, EXPORT):
        entries = {e["id"]: e for e in yaml.safe_load(path.read_text())["services"]}
        e = entries.get("svc_nos-forum")
        assert e, f"{path.name} lacks svc_nos-forum"
        assert e["flag"] == "install_nos_forum"
    erase = {e["id"]: e for e in yaml.safe_load(ERASURE.read_text())["services"]}["svc_nos-forum"]
    assert "erase_subject" in erase["note"], "erasure must name the module reducer that does it"
    assert "svc_nos-forum" in REGISTER.read_text(encoding="utf-8")


def test_policy_doc_matches_the_register_row():
    text = DOC.read_text(encoding="utf-8")
    g = _plugin()["gdpr"]
    assert f"**{g['retention_days']} days**" in text
    assert g["legal_basis"] in text
    assert "not enforced in v0.1" in text, "the doc must not read as if retention runs"
    readme = (REPO / "docs/systems/nos-forum/README.md").read_text(encoding="utf-8")
    assert "docs/compliance/nos-forum.md" in readme


def test_flag_ships_off():
    cfg = yaml.safe_load((REPO / "default.config.yml").read_text(encoding="utf-8"))
    assert cfg["install_nos_forum"] is False
    assert cfg["nos_forum_calls_enabled"] is False
