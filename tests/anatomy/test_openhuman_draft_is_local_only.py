"""The staged OpenHuman core stays local, and its reader tells OK from RED from UNKNOWN.

WHY. OpenHuman ships with cloud defaults: privacy `standard`, analytics on
(Sentry), usage sharing on, self-update over RPC on. apps/openhuman.yml.draft
turns each off; a later edit that drops one line would put the estate's agent
on the cloud route with nothing failing. Promotion (`.draft` -> `.yml`) keeps
this gate, because it reads whichever of the two files exists.

WHAT IS PINNED. privacy.mode = local_only; analytics_enabled = false (env and
config.toml); update mutations off; no route (no Traefik label, loopback-only
port, `nginx.route: false`); `gdpr.processors: []`. Each is shown red on a copy
missing it. Plus `tools/openhuman-status.py --selftest` (fixture configs).
"""

from __future__ import annotations

import copy
import importlib.util
import pathlib
import subprocess
import sys
import tomllib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
DRAFT = next((p for p in (REPO / "apps/openhuman.yml", REPO / "apps/openhuman.yml.draft")
              if p.exists()), REPO / "apps/openhuman.yml.draft")


def violations(doc: dict) -> list[str]:
    out = []
    svc = doc["compose"]["services"]["openhuman"]
    env = dict(e.split("=", 1) for e in svc.get("environment", []))
    toml = tomllib.loads(doc["compose"]["configs"]["openhuman_config"]["content"])
    if toml.get("privacy", {}).get("mode") != "local_only":
        out.append("privacy.mode is not local_only")
    if env.get("OPENHUMAN_ANALYTICS_ENABLED") != "false" or \
            toml.get("observability", {}).get("analytics_enabled") is not False:
        out.append("analytics not off in both env and config.toml")
    if env.get("OPENHUMAN_AUTO_UPDATE_RPC_MUTATIONS_ENABLED") != "false" or \
            toml.get("update", {}).get("rpc_mutations_enabled") is not False:
        out.append("update RPC mutations not off")
    if any("traefik" in str(lbl) for lbl in svc.get("labels", []) or []):
        out.append("a Traefik label = a route")
    if any(not str(p).startswith("127.0.0.1:") for p in svc.get("ports", [])):
        out.append("a port published beyond loopback")
    if (doc.get("nginx") or {}).get("route") is not False:
        out.append("nginx.route is not false")
    if doc["gdpr"].get("processors") != []:
        out.append("gdpr.processors is not []")
    return out


@pytest.fixture(scope="module")
def doc() -> dict:
    return yaml.safe_load(DRAFT.read_text(encoding="utf-8"))


def test_the_draft_is_local_only(doc):
    assert violations(doc) == []


def _edit_config(d: dict, old: str, new: str) -> dict:
    cfg = d["compose"]["configs"]["openhuman_config"]
    assert old in cfg["content"], old
    cfg["content"] = cfg["content"].replace(old, new)
    return d


BREAKS = {
    "privacy": lambda d: _edit_config(d, 'mode = "local_only"', 'mode = "standard"'),
    "analytics": lambda d: d["compose"]["services"]["openhuman"]["environment"].remove(
        "OPENHUMAN_ANALYTICS_ENABLED=false"),
    "updater": lambda d: _edit_config(d, "rpc_mutations_enabled = false", "rpc_mutations_enabled = true"),
    "route-label": lambda d: d["compose"]["services"]["openhuman"].__setitem__(
        "labels", ["traefik.enable=true"]),
    "route-port": lambda d: d["compose"]["services"]["openhuman"].__setitem__("ports", ["7788:7788"]),
    "route-flag": lambda d: d["nginx"].pop("route"),
    "processors": lambda d: d["gdpr"].__setitem__("processors", ["TinyHumans"]),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_each_missing_pin_goes_red(doc, name):
    broken = copy.deepcopy(doc)
    BREAKS[name](broken)
    assert violations(broken), f"{name}: the gate stayed green on a copy missing it"


def test_the_draft_is_not_discovered_by_the_runner():
    """`.draft` is the off switch: the runner globs *.yml and also excludes *.draft."""
    tasks = (REPO / "roles/pazny.apps_runner/tasks/main.yml").read_text(encoding="utf-8")
    assert "'*.draft'" in tasks and DRAFT.name.endswith((".draft", ".yml"))


def test_the_reader_selftest_passes():
    r = subprocess.run([sys.executable, str(REPO / "tools/openhuman-status.py"), "--selftest"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "selftest ok" in r.stdout, r.stdout + r.stderr


def test_the_reader_reports_unknown_without_a_config(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ohs", REPO / "tools/openhuman-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("NOS_OPENHUMAN_DIR", str(tmp_path))
    monkeypatch.setenv("NOS_OPENHUMAN_APP", str(tmp_path / "none.app"))
    rows = {r["check"]: r["state"] for r in mod.collect()}
    assert rows["privacy mode"] == mod.UNKNOWN and rows["analytics"] == mod.UNKNOWN
    assert mod.OK not in {rows[k] for k in ("privacy mode", "model route", "memory", "MCP servers")}


def test_the_reader_is_red_on_a_brew_record_without_its_app(tmp_path, monkeypatch):
    """Caskroom/openhuman with no OpenHuman.app read 'installed: OK' (2026-10-09)."""
    spec = importlib.util.spec_from_file_location("ohs", REPO / "tools/openhuman-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (tmp_path / "Caskroom/openhuman").mkdir(parents=True)
    monkeypatch.setenv("NOS_OPENHUMAN_DIR", str(tmp_path))
    monkeypatch.setenv("NOS_OPENHUMAN_APP", str(tmp_path / "none.app"))
    monkeypatch.setenv("NOS_OPENHUMAN_CASKROOM", str(tmp_path / "Caskroom/openhuman"))
    assert {r["check"]: r["state"] for r in mod.collect()}["installed"] == mod.RED


LOCAL = 'memory_provider = "ollama:x"\nembeddings_provider = "ollama:x"\n[memory]\nembedding_provider = "ollama"\n'


@pytest.mark.parametrize("memory, state", [
    ("", "RED"),                                                       # unset = tinyhumans, the cloud engine
    ('engine = "tinyhumans"\n', "RED"),
    ('engine = "none"\n', "OK"),
    ('engine = "none"\nauto_save = true\n', "OK"),                      # a dead key decides nothing
    ('engine = "cortexdb"\n[memory.engines.cortexdb]\nendpoint = "http://127.0.0.1:8091/hippocampus"\n'
     '[memory.recall]\nenabled = true\n', "OK"),
    ('engine = "cortexdb"\n[memory.engines.cortexdb]\nendpoint = "https://cortex.example.com"\n', "RED"),
])
def test_the_reader_judges_the_memory_engine(memory, state):
    """v0.64.15 has no local memory store: `memory.engine` binds tinyhumans (cloud), cortexdb
    (any endpoint) or none. The reader judged `auto_save`, a key the app ignores."""
    spec = importlib.util.spec_from_file_location("ohs", REPO / "tools/openhuman-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = tomllib.loads(LOCAL + memory)
    row = next(r for r in mod.judge_config(cfg, "f") if r["check"] == "memory")
    assert row["state"] == getattr(mod, state), row


def test_the_reader_judges_default_model_like_a_route():
    """The session clones default_model over chat_provider; `hermes3:8b` reads as provider hermes3."""
    spec = importlib.util.spec_from_file_location("ohs", REPO / "tools/openhuman-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    good = 'chat_provider = "ollama:x"\nreasoning_provider = "ollama:x"\nagentic_provider = "ollama:x"\n' \
           'coding_provider = "ollama:x"\n'
    route = lambda extra: next(r for r in mod.judge_config(tomllib.loads(extra + good), "f") if r["check"] == "model route")  # noqa: E731
    assert route('default_model = "hermes3:8b"\n')["state"] == mod.RED
    assert route('default_model = "ollama:hermes3:8b"\n')["state"] == mod.OK
