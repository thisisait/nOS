"""The live Art-30 record names the processor THIS host serves, never the union.

WHY. state/dpa-register.md is "what may bind": iris names Mistral AND this host. Wing's /gdpr
upserted the same union, so a host that chose iris_backend: ollama still told its DPO that
Mistral processes the rows. nos_gdpr.effective_records() keeps only the processors of the rows
that serve here (chosen or declared, plus an armed fallback), recomputes transfers_outside_eu
from their residency and stamps active + served_by. An unarmed choice serves nothing: no
processor, active false. A non-EU row under an EU claim serves only at gdpr_posture: none.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import yaml

from module_utils import nos_gdpr  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKENDS = yaml.safe_load((REPO / "state/habitat/llm-backends.yml").read_text())["backends"]
POST = REPO / "roles/pazny.wing/tasks/post.yml"
WING = REPO / "files/anatomy/wing"


def _records():
    return nos_gdpr.records_from_agents(REPO / "files/anatomy/agents")


def _one(name, **choices):
    base = {"armed": set(), "cells": {}, "agents_backend": "", "posture": "standard",
            "flags": {"install_thalamus": True, "install_loops": True, "install_wing": True}}
    base.update(choices)
    rec = next(r for r in nos_gdpr.effective_records(_records(), base, BACKENDS)
               if r["id"] == f"agent_{name}")
    return rec, [p["name"] for p in rec["processors"]]


def test_iris_on_the_host_names_only_the_host():
    rec, names = _one("iris", armed={"ollama"}, cells={"iris": "ollama"})
    assert names == ["This host (on-device, Ollama)"]
    assert rec["transfers_outside_eu"] == 0
    assert rec["served_by"] == "ollama" and rec["active"] is True


def test_iris_on_its_declared_row_names_mistral():
    rec, names = _one("iris", armed={"mistral-eu"})
    assert len(names) == 1 and "Mistral" in names[0]
    assert rec["served_by"] == "mistral-eu" and rec["transfers_outside_eu"] == 0


def test_an_unarmed_choice_serves_nothing():
    rec, names = _one("iris", armed={"mistral-eu"}, cells={"iris": "ollama"})
    assert names == [] and rec["served_by"] == "" and rec["active"] is False


def test_a_row_the_cell_does_not_allow_serves_nothing():
    rec, names = _one("iris", armed={"minimax"}, cells={"iris": "minimax"}, posture="none")
    assert names == [] and rec["active"] is False


def test_the_owner_switch_off_is_inactive():
    rec, _ = _one("iris", armed={"ollama"}, cells={"iris": "ollama"}, flags={"install_thalamus": False})
    assert rec["active"] is False and rec["served_by"] == "ollama"


def _eu_cell_on(row, posture):
    rec = {"id": "agent_c", "processors": [{"name": "Mistral AI SAS"}, {"name": "MiniMax"}],
           "transfers_outside_eu": 0,
           "binding": {"backend": "mistral-eu", "backends_allowed": ["mistral-eu", "minimax"],
                       "primary": "openai-sonnet", "owner": None}}
    choices = {"armed": {row}, "cells": {"c": row}, "agents_backend": "", "posture": posture, "flags": {}}
    return nos_gdpr.effective_records([rec], choices, BACKENDS)[0]


def test_a_non_eu_row_under_an_eu_claim_serves_only_at_posture_none():
    refused = _eu_cell_on("minimax", "standard")
    assert refused["processors"] == [] and refused["active"] is False
    served = _eu_cell_on("minimax", "none")
    assert [p["name"] for p in served["processors"]] == ["MiniMax"]
    assert served["transfers_outside_eu"] == 1 and served["served_by"] == "minimax"


def test_a_disarmed_row_names_the_default_that_serves():
    # minimax not armed: BindingResolver runs jeff-cloud on the default, so Anthropic is named
    rec, names = _one("jeff-cloud")
    assert rec["served_by"] == "anthropic" and rec["transfers_outside_eu"] == 1
    assert any("Anthropic" in n for n in names) and not any("MiniMax" in n for n in names)


def test_a_plugin_record_passes_through():
    rec = {"id": "svc_x", "processors": [{"name": "Anthropic"}], "transfers_outside_eu": 1}
    assert nos_gdpr.effective_records([rec], {}, BACKENDS) == [rec]


def test_the_converge_refuses_iris_on_a_non_eu_row_at_posture_standard():
    spec = importlib.util.spec_from_file_location("nos_cell_binding", REPO / "tools/nos_cell_binding.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    env = {"NOS_CELL_BACKEND": "minimax", "NOS_ARMED_BACKENDS": "minimax", "NOS_GDPR_POSTURE": "standard"}
    why = mod.requirement(REPO, "install_thalamus", "iris", env.get, 3)
    assert why and "gdpr_posture" in why and "minimax" in why


def test_iris_on_a_non_eu_cloud_row_is_recorded_only_where_the_posture_allows():
    """Ruling 2026-10-17: iris may use anthropic-api / minimax-api; a client host on standard serves neither."""
    for row, who in (("anthropic-api", "Anthropic"), ("minimax-api", "MiniMax")):
        rec, names = _one("iris", armed={row}, cells={"iris": row}, posture="standard")
        assert names == [] and rec["active"] is False, (row, names)
        rec, names = _one("iris", armed={row}, cells={"iris": row}, posture="none")
        assert len(names) == 1 and who in names[0], (row, names)
        assert rec["transfers_outside_eu"] == 1 and rec["served_by"] == row


def test_the_converge_refuses_iris_on_the_new_cloud_rows_at_posture_standard():
    spec = importlib.util.spec_from_file_location("nos_cell_binding", REPO / "tools/nos_cell_binding.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for row in ("anthropic-api", "minimax-api"):
        env = {"NOS_CELL_BACKEND": row, "NOS_ARMED_BACKENDS": row, "NOS_GDPR_POSTURE": "standard"}
        why = mod.requirement(REPO, "install_thalamus", "iris", env.get, 3)
        assert why and "gdpr_posture" in why and row in why, (row, why)
        assert mod.requirement(REPO, "install_thalamus", "iris", {**env, "NOS_GDPR_POSTURE": "none"}.get, 3) is None


def test_the_records_tool_emits_the_resolved_host_set():
    out = subprocess.run([sys.executable, str(REPO / "tools/gdpr-records.py"), "--tier", "host", "--resolved"],
                         capture_output=True, text=True, timeout=120, check=True).stdout
    rows = {r["id"]: r for r in yaml.safe_load(out)}
    assert "svc_wing" in rows and "agent_iris" in rows
    assert {"active", "served_by"} <= set(rows["agent_iris"])


def test_the_records_tool_honours_the_converge_vars():
    # -e / profile values reach the tool through NOS_GDPR_VARS, not only the layer files
    tool = [sys.executable, str(REPO / "tools/gdpr-records.py")]
    names = json.loads(subprocess.run([*tool, "--choice-vars"], capture_output=True, text=True,
                                      timeout=120, check=True).stdout)
    assert {"iris_backend", "install_thalamus", "ollama_enabled", "install_ollama"} <= set(names)
    # every other backend off, so a host whose config.yml arms one (mistral_enabled) reads the same
    off = {n: False for n in names if n.endswith("_enabled") and n != "ollama_enabled"}
    env = {**os.environ, "NOS_GDPR_VARS": json.dumps({**off, "install_thalamus": True, "install_ollama": True,
                                                      "ollama_enabled": True, "iris_backend": "ollama"})}
    out = subprocess.run([*tool, "--tier", "host", "--resolved"], capture_output=True, text=True,
                         timeout=120, check=True, env=env).stdout
    iris = next(r for r in json.loads(out) if r["id"] == "agent_iris")
    assert iris["served_by"] == "ollama" and iris["active"] is True


def test_wing_hands_the_converge_vars_to_the_tool():
    tasks = yaml.safe_load(POST.read_text())
    cmd = next(t for t in tasks if "Emit Tier-1 GDPR" in str(t.get("name")))
    assert "query('vars'" in str(cmd.get("environment", {}).get("NOS_GDPR_VARS", ""))
    assert any("--choice-vars" in str(t) for t in tasks)


def test_wing_upserts_the_resolved_rows_with_both_columns():
    cmd = next(t for t in yaml.safe_load(POST.read_text()) if "Emit Tier-1 GDPR" in str(t.get("name")))
    assert "--resolved" in str(cmd["ansible.builtin.command"]["cmd"])
    php = (WING / "bin/upsert-gdpr.php").read_text()
    assert "'served_by'" in php and "'active'" in php
    for f in ("db/schema-extensions.sql", "bin/init-db.php"):
        text = (WING / f).read_text()
        assert "served_by" in text and "active" in text.split("gdpr_processing", 1)[-1], f


def test_gdpr_posture_defaults_to_standard():
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity
    assert nos_identity.resolved({"gdpr_posture"}, nos_identity.default_layers())["gdpr_posture"] == "standard"
