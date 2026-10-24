"""Three switches put a model on the host; the size floors read the same everywhere.

Ruling 2026-10-16 (definition A, rulings 2+3): `llm_on_host` (default true, also in
profiles/core.yml), `vlm_on_host`, `decision_model_on_host` are defaults over the existing
knobs, so Iris works on a fresh host with no key ("even badly", on qwen3:4b). A later layer
still sets a cloud row. A model under llm_cell_min_params_b (3) or of unknown size refuses;
under llm_cell_recommended_params_b (8) it warns. Three readers judge it: tools/nos_cell_binding.py
(converge preflight), src/binding.rs (Iris at session open), tools/job_readiness.py (Pulse fire time);
the first two run the `sizes:` cases of binding-cases.yml.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity  # noqa: E402

CASES = REPO / "files/anatomy/thalamus/thalamus/tests/binding-cases.yml"
NAMES = ("llm_on_host", "vlm_on_host", "decision_model_on_host", "ollama_enabled", "ollama_model",
         "ollama_vision_model", "vlm_model", "ollama_decision_model", "iris_backend", "agents_backend", "install_ollama", "ollama_small_model")


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, REPO / path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _resolved(tmp_path, top: str = "") -> dict:
    """The committed layers, plus `top` as the host's config.yml."""
    paths = [p for p in nos_identity.layer_paths() if p.name != "config.yml"]
    if top:
        (tmp_path / "config.yml").write_text(top)
        paths.append(tmp_path / "config.yml")
    return nos_identity.resolved(NAMES, paths)


def test_the_switches_and_floors_are_default_layer_vars():
    cfg = nos_identity.default_config()
    assert (cfg["llm_on_host"], cfg["decision_model_on_host"]) == (True, False)
    assert cfg["vlm_on_host"] == "{{ ollama_vision_model != '' }}", "W1: the vision switch follows a named model"
    assert (cfg["llm_cell_min_params_b"], cfg["llm_cell_recommended_params_b"]) == (3, 8)
    floors = yaml.safe_load(CASES.read_text())["floors"]
    assert floors == {"min_b": 3, "warn_b": 8}, "the shared cases judge other floors than the defaults"


def test_a_fresh_host_binds_iris_on_device(tmp_path):
    got = _resolved(tmp_path)
    assert got["ollama_enabled"] is True and got["install_ollama"] is True
    assert (got["ollama_model"], got["iris_backend"]) == ("qwen3:4b", "ollama")
    assert (got["ollama_vision_model"], got["ollama_decision_model"]) == ("", "")
    assert got["agents_backend"] == "", "agents keep their own rows (ruling R4)"
    assert got["ollama_small_model"] == "hermes3:8b", "both small models stay (ruling R3)"


def test_each_switch_names_its_model(tmp_path):
    got = _resolved(tmp_path, "llm_on_host: false\nvlm_on_host: true\ndecision_model_on_host: true\n")
    assert got["ollama_enabled"] is True and (got["ollama_model"], got["iris_backend"]) == ("", "")
    assert (got["vlm_model"], got["ollama_decision_model"]) == ("qwen2.5vl:7b", "tev1:4b")
    off = _resolved(tmp_path, "llm_on_host: false\n")
    assert off["ollama_enabled"] is False and off["iris_backend"] == ""


def test_a_later_layer_still_sets_a_cloud_row(tmp_path):
    got = _resolved(tmp_path, "iris_backend: mistral-eu\nollama_model: qwen3:14b\n")
    assert (got["iris_backend"], got["ollama_model"], got["ollama_enabled"]) == ("mistral-eu", "qwen3:14b", True)


def test_the_core_profile_keeps_the_model_on_the_host():
    core = yaml.safe_load((REPO / "profiles/core.yml").read_text())
    assert core.get("llm_on_host") is True
    assert core.get("install_ollama", True) is True, "core turns off the daemon its Iris binds"


def test_the_decision_model_is_pulled():
    pull = yaml.safe_load((REPO / "roles/pazny.ollama/defaults/main.yml").read_text())["ollama_pull_models"]
    assert "ollama_decision_model" in pull


@pytest.mark.parametrize("case", yaml.safe_load(CASES.read_text())["sizes"], ids=lambda c: c["model"] or "empty")
def test_the_preflight_judges_size_like_the_shared_cases(case):
    floors = yaml.safe_load(CASES.read_text())["floors"]
    refusal, warning = _load("nos_cell_binding", "tools/nos_cell_binding.py").size_floor(
        case["model"], floors["min_b"], floors["warn_b"])
    got = "refused" if refusal else "warned" if warning else "silent"
    assert got == case["expect"], (case, refusal, warning)
    assert case.get("contains", "") in (refusal or warning or ""), (case, refusal or warning)


def test_the_rust_binding_runs_the_size_cases():
    src = (REPO / "files/anatomy/thalamus/thalamus/tests/binding.rs").read_text()
    assert "binding_judges_size_like_the_shared_cases" in src and '"sizes"' in src


def test_the_thalamus_gets_both_floors():
    benv = yaml.safe_load((REPO / "roles/pazny.thalamus/defaults/main.yml").read_text())["thalamus_binding_env"]
    assert "llm_cell_min_params_b" in benv["NOS_LLM_MIN_PARAMS_B"]
    assert "llm_cell_recommended_params_b" in benv["NOS_LLM_RECOMMENDED_PARAMS_B"]
    task = (REPO / "roles/pazny.thalamus/tasks/llm-requirement.yml").read_text()
    assert "--warn-below-b {{ llm_cell_recommended_params_b }}" in task


CFG = {"ollama_enabled": "true", "ollama_small_model": "hermes3:8b", "vlm_model": "",
       "minimax_enabled": "false", "install_claude_cli_vendor": "false", "agents_backend": "ollama",
       "llm_cell_min_params_b": "3", "llm_cell_recommended_params_b": "8"}


@pytest.mark.parametrize("model,held,warned", [
    ("qwen3:4b", False, True), ("hermes3:8b", False, False), ("qwen3:1.7b", True, False), ("qwen3:latest", True, False),
])
def test_pulse_holds_below_the_floor_and_warns_below_the_recommendation(model, held, warned):
    j = _load("_job_readiness_onhost", "tools/job_readiness.py")
    host = {"claude": None, "ollama_models": {model}, "anthropic_key": False}
    needs = j.agent_needs("librarian", {**CFG, "ollama_model": model}, host)
    assert bool([n for n in needs if not n.warn]) is held, needs
    assert bool([n for n in needs if n.warn]) is warned, needs
    assert (j.hold(agents=("librarian",), cfg={**CFG, "ollama_model": model}, host=host) == j.HOLD_EXIT) is held


VISION = ("files/anatomy/plugins/invoice-vision-base/plugin.yml", "files/anatomy/agents/invoice-extract/agent.yml",
          "files/anatomy/agents/invoice-vision-ocr/agent.yml")


def test_the_vision_work_is_owned_by_vlm_on_host():
    """Ruling R2: invoice vision needs the VLM, not just the daemon."""
    docs = [yaml.safe_load((REPO / p).read_text()) for p in VISION]
    assert [docs[0]["requires"]["feature_flag"], docs[1]["owner"], docs[2]["owner"]] == ["vlm_on_host"] * 3


def test_install_flags_read_the_on_host_switches():
    flags = nos_identity.install_flags(nos_identity.profile_layers(REPO / "profiles/core.yml"))
    assert (flags.get("llm_on_host"), flags.get("vlm_on_host"), flags.get("decision_model_on_host")) == (True, False, False)
    post = (REPO / "roles/pazny.wing/tasks/post.yml").read_text()
    assert "_on_host" in next(l for l in post.splitlines() if "NOS_INSTALL_FLAGS:" in l), "Pulse never sees the switch"


def test_all_on_runs_the_vision_work():
    """all-on is every known-good service; invoice intake is one since R2 moved it to vlm_on_host."""
    assert yaml.safe_load((REPO / "profiles/all-on.yml").read_text()).get("vlm_on_host") is True


@pytest.mark.parametrize("cfg,warned", [
    ({"vlm_on_host": False, "ollama_vision_model": "qwen2.5vl:7b"}, True),
    ({"vlm_on_host": False, "ollama_vision_model": ""}, False),
    ({"vlm_on_host": True, "ollama_vision_model": "qwen2.5vl:7b"}, False),
])
def test_a_vision_model_with_its_switch_off_warns(cfg, warned):
    """A host that names a vision model but not vlm_on_host loses invoice intake; the converge says so."""
    import jinja2
    plays = yaml.safe_load((REPO / "main.yml").read_text())
    tasks = [t for p in plays for t in p.get("tasks", []) + p.get("pre_tasks", [])]
    task = next((t for t in tasks if "vlm_on_host" in str(t.get("name", ""))), None)
    assert task is not None, "no converge task warns about a vision model with vlm_on_host off"
    env = jinja2.Environment()
    whens = task["when"] if isinstance(task["when"], list) else [task["when"]]
    assert all(env.compile_expression(w)(**cfg) for w in whens) is warned


def test_a_named_vision_model_arms_the_switch(tmp_path):
    """W1: a config.yml that names a vision model (from before the switches) keeps invoice intake."""
    got = _resolved(tmp_path, 'ollama_vision_model: "qwen2.5vl:3b"\n')
    assert (got["vlm_on_host"], got["vlm_model"], got["ollama_enabled"]) == (True, "qwen2.5vl:3b", True)
    paths = [p for p in nos_identity.layer_paths() if p.name != "config.yml"] + [tmp_path / "config.yml"]
    assert nos_identity.install_flags(paths).get("vlm_on_host") is True, "readers miss the armed switch"
    alone = _resolved(tmp_path, "vlm_on_host: true\n")
    assert alone["vlm_model"] == "qwen2.5vl:7b", "the switch alone names no model"
    assert _resolved(tmp_path)["vlm_model"] == "", "a fresh host serves a vision model"


def test_the_model_vars_do_not_loop():
    """Ansible refuses a var that reaches itself; nos_identity.resolved() reads the loop as a string."""
    from jinja2 import Environment, meta
    cfg, env = nos_identity.default_config(), Environment()
    deps = {k: meta.find_undeclared_variables(env.parse(v)) & cfg.keys()
            for k, v in cfg.items() if isinstance(v, str) and "{{" in v}

    def reaches(start, name, seen=()):
        return any(d == start or (d not in seen and reaches(start, d, (*seen, d))) for d in deps.get(name, ()))
    assert not [n for n in NAMES if reaches(n, n)], "a model var loops"
