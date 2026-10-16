"""A service whose cell is bound to a local model refuses to converge without one big enough.

install_thalamus needs cell iris. Bound to ollama (local), if ollama is not enabled, or the model
it would bind is under llm_cell_min_params_b (3, ruling 2026-10-16) or of unknown size, the converge refuses in
preflight — before anything is built — naming the service, cell, model, why, and the two fixes.
A cloud-bound cell (iris on mistral-eu, ruling 2026-10-12) needs no ollama. The check reuses the thalamus's binding:
tools/nos_cell_binding.py ports src/binding.rs, and both run tests/binding-cases.yml.
OpenHuman binds no cell (openhuman_provider, no agent.yml), so it is not checked.
"""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import sys

import jinja2
import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
HELPER = REPO / "tools/nos_cell_binding.py"
CASES = REPO / "files/anatomy/thalamus/thalamus/tests/binding-cases.yml"
ROLE = REPO / "roles/pazny.thalamus"
REGISTER = (REPO / "state/habitat/llm-backends.yml").read_text()


def _helper():
    spec = importlib.util.spec_from_file_location("nos_cell_binding", HELPER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # @dataclass resolves its module by name
    spec.loader.exec_module(mod)
    return mod


def _env(**pairs):
    return lambda k: pairs.get(k)


@pytest.mark.parametrize("tag,size", [
    ("qwen3:14b", 14), ("hermes3:8b", 8), ("llama3.2:3b", 3), ("mixtral:8x7b", 56), ("phi3:3.8b", 3.8),
    ("gemma3:270m", 0.27), ("qwen3:14b-q4_K_M", 14), ("qwen2.5vl:7b", 7), ("qwen3:30b-a3b", 30),
    ("qwen3:latest", None), ("qwen3", None), ("hermes3", None), ("gemma3n:e2b", None), ("", None),
    ("llama3-8b:latest", None),
])
def test_params_b_reads_the_tag_or_says_unknown(tag, size):
    got = _helper().params_b(tag)
    assert got == pytest.approx(size) if size is not None else got is None, (tag, got)


def test_the_port_agrees_with_the_rust_resolver_on_the_shared_cases():
    """tests/binding.rs binding_agrees_with_the_shared_cases runs the same file against binding.rs."""
    h = _helper()
    cases = yaml.safe_load(CASES.read_text())["cases"]
    assert len(cases) >= 10
    for c in cases:
        agent = (REPO / "files/anatomy/agents" / c["cell"] / "agent.yml").read_text() if "cell" in c else c["agent"]
        d, want = h.decide(agent, REGISTER, (c["env"] or {}).get), c["expect"]
        assert d.kind == want["kind"], (c["name"], d)
        if d.kind == "bound":
            assert d.model_id == want["model_id"], c["name"]
        elif d.kind == "disarmed":
            assert d.backend == want["backend"], c["name"]
        elif d.kind == "refused":
            assert want["contains"] in d.why, (c["name"], d.why)
    assert "binding_agrees_with_the_shared_cases" in (REPO / "files/anatomy/thalamus/thalamus/tests/binding.rs").read_text()


LOCAL_IRIS = ("name: iris\nmodel: {primary: openai-local-sonnet, backend: ollama}\n"
              "gdpr: {processors: [{name: on-device}], transfers_outside_eu: false}\n")


@pytest.fixture
def local_repo(tmp_path):
    """A repo where iris is bound to ollama: the real register, a local iris."""
    (tmp_path / "files/anatomy/agents/iris").mkdir(parents=True)
    (tmp_path / "files/anatomy/agents/iris/agent.yml").write_text(LOCAL_IRIS)
    (tmp_path / "state/habitat").mkdir(parents=True)
    shutil.copy(REPO / "state/habitat/llm-backends.yml", tmp_path / "state/habitat/llm-backends.yml")
    return tmp_path


def test_the_real_iris_is_cloud_bound_and_passes_without_ollama():
    """Iris binds mistral-eu (ruling 2026-10-12): install_thalamus converges with ollama off."""
    assert _helper().requirement(REPO, "install_thalamus", "iris", _env(), 8) is None
    assert _helper().requirement(REPO, "install_thalamus", "iris", _env(NOS_ARMED_BACKENDS="mistral-eu"), 8) is None


def test_iris_with_a_big_enough_local_model_passes(local_repo):
    _iris = lambda **env: _helper().requirement(local_repo, "install_thalamus", "iris", _env(**env), 8)  # noqa: E731
    assert _iris(NOS_ARMED_BACKENDS="ollama", NOS_LOCAL_MODEL="qwen3:14b") is None
    assert _iris(NOS_ARMED_BACKENDS="ollama", NOS_LOCAL_MODEL="hermes3:8b") is None


@pytest.mark.parametrize("env,model,why", [
    ({"NOS_ARMED_BACKENDS": "ollama", "NOS_LOCAL_MODEL": "llama3.2:3b"}, "llama3.2:3b", "3B parameters, below the 8B minimum"),
    ({"NOS_ARMED_BACKENDS": "ollama", "NOS_LOCAL_MODEL": "qwen3:latest"}, "qwen3:latest", "UNKNOWN"),
    ({"NOS_LOCAL_MODEL": "qwen3:14b"}, "qwen3:14b", "ollama is not enabled"),
    ({}, "(none set)", "ollama is not enabled"),
    ({"NOS_ARMED_BACKENDS": "ollama"}, "(none set)", "NOS_LOCAL_MODEL is empty"),
])
def test_iris_refuses_with_service_cell_model_why_and_both_fixes(local_repo, env, model, why):
    text = _helper().requirement(local_repo, "install_thalamus", "iris", _env(**env), 8)
    assert text, f"{env} was not refused"
    for part in ("install_thalamus", "'iris'", f"would bind is {model}", why,
                 "ollama_enabled: true", "ollama_model:", "hermes3:8b",
                 "files/anatomy/agents/iris/agent.yml", "cloud backend"):
        assert part in text, f"{part!r} missing from:\n{text}"


def test_a_cloud_bound_cell_needs_no_ollama(tmp_path):
    cell = tmp_path / "files/anatomy/agents/c"
    cell.mkdir(parents=True)
    (cell / "agent.yml").write_text("name: c\nmodel: {primary: claude-sonnet, backend: minimax}\n"
                                    "gdpr: {processors: [{name: MiniMax}], transfers_outside_eu: true}\n")
    (tmp_path / "state/habitat").mkdir(parents=True)
    shutil.copy(REPO / "state/habitat/llm-backends.yml", tmp_path / "state/habitat/llm-backends.yml")
    assert _helper().requirement(tmp_path, "install_x", "c", _env(), 8) is None
    (cell / "agent.yml").write_text("name: c\nmodel: {primary: claude-sonnet}\n")
    assert _helper().requirement(tmp_path, "install_x", "c", _env(), 8) is None


def _default_config() -> dict:
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity
    return nos_identity.default_config()


def test_the_minimum_is_a_default_layer_var():
    assert _default_config()["llm_cell_min_params_b"] == 3


def test_the_preflight_runs_before_anything_is_built():
    """In pre_tasks, tagged always, only when install_thalamus is on, through the role's own env."""
    play = yaml.safe_load((REPO / "main.yml").read_text())[0]
    pre = play["pre_tasks"]
    step = next((t for t in pre if (t.get("ansible.builtin.include_role") or {}).get("tasks_from") == "llm-requirement.yml"), None)
    assert step, "no LLM-cell preflight in main.yml pre_tasks"
    assert step["ansible.builtin.include_role"]["name"] == "pazny.thalamus"
    assert {"always", "preflight"} <= set(step["tags"]) and {"always", "preflight"} <= set(
        step["ansible.builtin.include_role"]["apply"]["tags"])
    assert "install_thalamus" in str(step["when"])
    task = yaml.safe_load((ROLE / "tasks/llm-requirement.yml").read_text())[0]
    cmd = str(task["ansible.builtin.command"])
    assert "tools/nos_cell_binding.py" in cmd and "--cell iris" in cmd and "llm_cell_min_params_b" in cmd
    assert task["environment"] == "{{ thalamus_binding_env }}"


def _render(text: str, **ctx) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = bool
    return env.from_string(text).render(**ctx)


def test_the_plist_and_the_preflight_read_one_binding_env():
    """The env the preflight judges is the env the daemon gets, and CONFIG_VAR names its sources."""
    ctx = {"ollama_enabled": True, "install_ollama": True, "ollama_model": "S-big", "ollama_small_model": "S-small"}
    benv = yaml.safe_load((ROLE / "defaults/main.yml").read_text())["thalamus_binding_env"]
    got = {k: _render(v, **ctx) for k, v in benv.items()}
    assert got["NOS_ARMED_BACKENDS"] == "ollama"
    assert _render(benv["NOS_ARMED_BACKENDS"], **{**ctx, "install_ollama": False}) == "", "no daemon, still armed"
    assert _render(benv["NOS_ARMED_BACKENDS"], **{**ctx, "ollama_enabled": False}) == ""
    for name, var in _helper().CONFIG_VAR.items():
        if name in got:
            assert got[name] == ctx[var], f"{name} is not filled from {var}"
    plist = (ROLE / "templates/thalamus.plist.j2").read_text()
    assert "thalamus_binding_env" in plist and "ollama_model" not in plist, "the plist renders a second env"


def test_the_real_iris_on_a_host_that_chose_ollama_is_judged_on_its_model():
    """Ruling 2026-10-14: iris_backend: ollama makes the real iris local, so the size gate applies."""
    req = lambda **env: _helper().requirement(REPO, "install_thalamus", "iris", _env(NOS_CELL_BACKEND="ollama", **env), 8)  # noqa: E731
    assert req(NOS_ARMED_BACKENDS="ollama", NOS_LOCAL_MODEL="qwen3:14b") is None
    assert "below the 8B minimum" in (req(NOS_ARMED_BACKENDS="ollama", NOS_LOCAL_MODEL="llama3.2:3b") or "")
