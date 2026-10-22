"""Gate: a reader learns WHAT RAN from ~/.nos/state.yml, not from the files.

Live host 2026-10-22: converges run `nos -e @profiles/core.yml -e
@profiles/workstation.yml -e '{"install_cortex": true}'`. profiles/core.yml
sets apps_runner_enabled: false, but no file layer shows an -e, so
nos_identity.installed_apps() still listed documenso/roundcube/twofauth,
tools/e2e-plan.py planned them, and the estate e2e read 21 red probes against
apps that were never deployed. state.yml is rewritten by every converge with
what the playbook actually resolved, -e included; the apps runner was the one
thing it did not record.

Three cases, and the writer:
  * present — the run said off: not installed, whatever the layers declare.
  * absent  — a fresh host, CI, a fork: the layers decide, and the reader says so.
  * unreadable — UNKNOWN, never a silent "everything on".
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
import nos_identity as ni  # noqa: E402
import nos_state_lib  # noqa: E402

_spec = importlib.util.spec_from_file_location("nos_smoke_ran", REPO / "tools/nos-smoke.py")
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)
_spec = importlib.util.spec_from_file_location("e2e_plan_ran", REPO / "tools/e2e-plan.py")
plan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plan_mod)

STATE_ENV = "NOS_STATE_FILE"  # the override every reader honours (nos_identity.STATE_ENV)
APPS = sorted(p.stem for p in (REPO / "apps").glob("[!_]*.yml"))
RAN_OFF = {
    "instance": {"tld": "example.test"},
    "last_run": {"run_id": "run_fixture", "at": "2026-10-22T12:00:00Z", "tag": "all"},
    "services": {"cortex": {"enabled": False}},
    "apps": {"runner_enabled": False, "deployed": []},
}


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A hermetic host: HOME and the state file are the test's, config.yml is absent."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(STATE_ENV, str(tmp_path / "state.yml"))
    monkeypatch.setattr(smoke, "operator_file", lambda name: tmp_path / name)
    monkeypatch.setattr(plan_mod.smoke, "operator_file", lambda name: tmp_path / name)
    return tmp_path


def _layers_on() -> dict:
    v = smoke.merge_config(*ni.default_layers())
    assert ni._on(v.get("apps_runner_enabled")), "fixture premise: the layers declare the runner on"
    return v


# ── present: the run's answer wins over the declaration ─────────────────────


def test_ran_off_is_not_installed_even_when_the_layers_say_on(host):
    (host / "state.yml").write_text(yaml.safe_dump(RAN_OFF))
    v = _layers_on()
    smoke.apply_runtime_estate(v, host / "config.yml", host / "state.yml", {"services": []})
    assert ni.installed_apps(v) == [], "the run did not deploy them; probing them reads red forever"


def test_ran_deploys_exactly_its_recorded_apps(host):
    state = {**RAN_OFF, "apps": {"runner_enabled": True, "deployed": APPS[:1]}}
    (host / "state.yml").write_text(yaml.safe_dump(state))
    v = _layers_on()
    smoke.apply_runtime_estate(v, host / "config.yml", host / "state.yml", {"services": []})
    assert ni.installed_apps(v) == APPS[:1]


def test_e2e_plan_plans_no_app_the_run_did_not_deploy(host):
    (host / "state.yml").write_text(yaml.safe_dump(RAN_OFF))
    planned = {r["plugin"] for r in plan_mod.plan()}
    assert not {f"apps/{a}.yml" for a in APPS} & planned, planned


def test_the_reader_names_the_run_it_read(host):
    (host / "state.yml").write_text(yaml.safe_dump(RAN_OFF))
    ran = ni.ran()
    assert ran.source == "state.yml"
    assert "run_fixture" in ran.provenance()


# ── absent: the layers decide, and the reader says so ───────────────────────


def test_no_state_file_means_the_layers_decide_and_say_so(host):
    ran = ni.ran()
    assert ran.source == "layers", ran
    assert "layers" in ran.provenance()
    v = _layers_on()
    smoke.apply_runtime_estate(v, host / "config.yml", host / "state.yml", {"services": []})
    assert ni.installed_apps(v) == APPS


def test_a_state_file_older_than_the_apps_record_leaves_apps_to_the_layers(host):
    (host / "state.yml").write_text(yaml.safe_dump({k: v for k, v in RAN_OFF.items() if k != "apps"}))
    v = _layers_on()
    smoke.apply_runtime_estate(v, host / "config.yml", host / "state.yml", {"services": []})
    assert ni.installed_apps(v) == APPS, "no record is not a record of off"


def test_e2e_plan_prints_its_provenance(host):
    out = subprocess.run([sys.executable, str(REPO / "tools/e2e-plan.py")], capture_output=True, text=True,
                         env={**os.environ, "HOME": str(host), STATE_ENV: str(host / "state.yml")},
                         timeout=120)
    assert out.returncode == 0, out.stderr
    assert "enablement: layers" in out.stderr, out.stderr


# ── unreadable: UNKNOWN, never everything-on ────────────────────────────────


@pytest.mark.parametrize("body", ["services: [unclosed\n", "- a list, not a mapping\n"])
def test_an_unreadable_state_file_is_unknown(host, body):
    (host / "state.yml").write_text(body)
    ran = ni.ran()
    assert ran.source == ni.UNKNOWN, ran
    assert ran.state == {}
    assert "UNKNOWN" in ran.provenance()


def test_estate_status_shows_the_run_beside_the_layers(host):
    def config(flag):
        return subprocess.run([sys.executable, str(REPO / "tools/estate-status.py"), "--config", flag],
                              capture_output=True, text=True, timeout=60,
                              env={**os.environ, STATE_ENV: str(host / "state.yml")}).stdout

    (host / "state.yml").write_text(yaml.safe_dump(RAN_OFF))
    for flag in ("install_cortex", "apps_runner_enabled"):
        out = config(flag)
        assert "run_fixture" in out and "==> false" in out.split("ran", 1)[-1], out
        assert "1 disagreement" in out, f"declared on, ran off — that must be visible:\n{out}"
    (host / "state.yml").write_text("services: [unclosed\n")
    assert "UNKNOWN" in config("install_cortex")
    (host / "state.yml").unlink()
    assert "no converge recorded" in config("install_cortex")


# ── the writer: every converge records the apps runner ──────────────────────


def _apps_dir(tmp_path) -> Path:
    d = tmp_path / "apps"
    d.mkdir()
    for name in ("_template.yml", "alpha.yml", "beta.yml", "gamma.yaml", "delta.yml.draft", "openhuman.yml"):
        (d / name).write_text("meta: {}\n")
    return d


def test_the_writer_records_what_the_runner_deploys(tmp_path):
    d = _apps_dir(tmp_path)
    rec = nos_state_lib.introspect_apps(str(d), {"apps_runner_enabled": True, "apps_skip": ["beta"],
                                                 "global_password_prefix": "never-copied"})
    assert rec == {"runner_enabled": True, "deployed": ["alpha", "gamma"]}, rec
    assert nos_state_lib.introspect_apps(str(d), {"apps_runner_enabled": "false"}) == \
        {"runner_enabled": False, "deployed": []}, "a string 'false' is off, as `| bool` reads it"
    assert "openhuman" in nos_state_lib.introspect_apps(str(d), {"install_openhuman": True})["deployed"]


def test_the_state_manager_passes_the_apps_dir():
    tasks = yaml.safe_load((REPO / "roles/pazny.state_manager/tasks/introspect.yml").read_text())
    call = next(t["nos_state"] for t in tasks if (t.get("nos_state") or {}).get("action") == "introspect")
    assert "apps_dir" in call, "the introspect call records no apps runner"
    schema = yaml.safe_load((REPO / "state/schema/state.schema.json").read_text())
    assert {"runner_enabled", "deployed"} <= set(schema["properties"]["apps"]["properties"])
