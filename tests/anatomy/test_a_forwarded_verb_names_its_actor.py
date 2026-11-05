"""A verb Wing forwards to Bone names the person who decided it.

WHY (roadmap `wing-tier-followups` item 4, measured 2026-10-07). Wing gates
apply / rollback / cutover / cleanup / provision / patch apply on wing.operator
and knows the person (user:<uid>), then called Bone with its own client bearer
and nothing else: the person stopped at Wing. Now BoneClient sends X-Nos-Actor,
Bone takes it only from Wing's client (azp nos-wing), hands it to the run as
nos_actor (invoke_playbook and the detached launcher), and the run's own
records name the person: the playbook-run notification and the engine's
reboot notice. 2026-11-05 review: nos_actor reached the CLI and no reader.

What runs: Bone's real main.py app over TestClient, JWT verification stubbed,
ansible-playbook replaced by a recorder; the real wing_telemetry callback with
its HTTP transport replaced. Nothing leaves the process.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import shlex
import sys

import jinja2
import yaml

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"
WING = REPO / "files/anatomy/wing/app"


@pytest.fixture()
def bone(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("jwt")
    from starlette.testclient import TestClient  # noqa: PLC0415

    monkeypatch.setenv("BONE_REQUIRE_JWT_AUTH", "0")
    monkeypatch.setenv("NOS_PATCHES_DIR", str(tmp_path))
    monkeypatch.syspath_prepend(str(BONE))
    # tests/{migrations,upgrades,state_manager} shadow Bone's bare module names.
    for name in ("migrations", "upgrades", "patches", "coexistence", "state", "events", "auth", "otel"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    (tmp_path / "PATCH-001.yml").write_text("id: PATCH-001\n")
    spec = importlib.util.spec_from_file_location("bone_main_under_test", BONE / "main.py")
    main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main)
    assert main._FRAMEWORK_READY, main.__dict__.get("_FRAMEWORK_IMPORT_ERROR")
    monkeypatch.setattr(sys.modules["auth"], "verify_token",
                        lambda token, required_scopes=(): {"azp": "other" if token == "foreign" else "nos-wing"})
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/nos-upgrade-detached.sh").write_text("")
    monkeypatch.setattr(sys.modules["migrations"], "PLAYBOOK_DIR", tmp_path)
    monkeypatch.setattr(sys.modules["upgrades"], "_validate", lambda s, r: None)

    runs: list[list[str]] = []
    envs: list[dict | None] = []

    class Proc:
        returncode = 0

        def __init__(self, cmd, env=None, **_):
            runs.append(cmd)
            envs.append(env)

        def communicate(self, timeout=None):  # noqa: ARG002
            return "ok", None

    monkeypatch.setattr(sys.modules["migrations"].subprocess, "Popen", Proc)
    return TestClient(main.app), runs, envs


def _apply(client, token="t", **headers):
    return client.post("/api/patches/PATCH-001/apply", headers={"Authorization": f"Bearer {token}", **headers})


def test_the_run_and_the_reply_name_the_person(bone):
    client, runs, _ = bone
    r = _apply(client, **{"X-Nos-Actor": "user:alice"})
    assert r.status_code == 200, r.text
    assert r.json()["actor"] == "user:alice"
    assert "nos_actor=user:alice" in runs[-1][runs[-1].index("--extra-vars") + 1]


def test_no_header_names_nobody_and_a_forged_one_is_refused(bone):
    client, runs, _ = bone
    r = _apply(client)
    assert r.status_code == 200 and r.json()["actor"] is None, r.text
    assert "nos_actor" not in " ".join(runs[-1])
    n = len(runs)
    assert _apply(client, **{"X-Nos-Actor": "user:a b --tags all"}).status_code == 400
    assert len(runs) == n, "a refused actor still ran the playbook"


def test_only_wings_client_may_name_a_person(bone):
    client, runs, _ = bone
    n = len(runs)
    assert _apply(client, token="foreign", **{"X-Nos-Actor": "user:alice"}).status_code == 403
    assert len(runs) == n, "a foreign bearer named a person and the playbook ran"
    assert _apply(client, token="foreign").status_code == 200, "a foreign bearer without the header is not Wing's concern"


def test_the_detached_run_names_the_person(bone):
    client, runs, envs = bone
    r = client.post("/api/upgrades/svc/rec/apply-detached",
                    headers={"Authorization": "Bearer t", "X-Nos-Actor": "user:alice"})
    assert r.status_code == 200, r.text
    assert runs[-1][-2:] == ["svc", "rec"] and (envs[-1] or {}).get("NOS_ACTOR") == "user:alice"
    sh = (REPO / "tools/nos-upgrade-detached.sh").read_text(encoding="utf-8")
    assert re.search(r'-e "nos_actor=\$\{NOS_ACTOR\}"', sh), "the launcher drops NOS_ACTOR"


def _telemetry():
    pytest.importorskip("ansible")
    spec = importlib.util.spec_from_file_location("wing_telemetry_actor", REPO / "callback_plugins/wing_telemetry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_run_record_names_the_person(monkeypatch):
    from ansible import context  # noqa: PLC0415
    from ansible.module_utils.common.collections import ImmutableDict  # noqa: PLC0415
    mod = _telemetry()
    sent: list[dict] = []

    class Http:
        def send_object(self, url, payload):  # noqa: ARG002
            sent.append(payload)

    def notify(extra_vars):
        monkeypatch.setattr(context, "CLIARGS", ImmutableDict(tags=("upgrade",), extra_vars=extra_vars))
        cb = mod.CallbackModule()
        cb._http, cb._url = Http(), "http://127.0.0.1:1/api/v1/events"
        cb._emit_failure_notification({"failed": 1}, 0)
        return sent[-1]["actor_id"]

    assert notify(("upgrade_service=svc nos_actor=user:alice",)) == "user:alice"
    assert notify(("upgrade_service=svc",)) == "operator"
    assert notify(('{"nos_actor": "user:a b"}',)) == "operator", "a malformed actor reached the record"


def test_the_engine_reboot_notice_names_the_person():
    tasks = yaml.safe_load((REPO / "tasks/upgrade-engine.yml").read_text(encoding="utf-8"))
    task = next(t for t in tasks if "reboot_required' notification" in t.get("name", ""))
    env = jinja2.Environment()
    env.filters["quote"] = lambda v: shlex.quote(str(v))
    tmpl = env.from_string(task["ansible.builtin.shell"]["cmd"])
    for ctx, want in (({"nos_actor": "user:alice"}, "user:alice"), ({}, "engine:upgrade")):
        cmd = tmpl.render(item={}, **ctx)
        arg = re.search(r"--arg (\w+) " + re.escape(want) + r" ", cmd)
        assert arg and re.search(r"actor_id: \$" + arg.group(1) + r",", cmd), (ctx, cmd)


#: Wing repository forwards that change the estate: each must hand Bone an actor.
FORWARDS = {
    "UpgradeRepository": ["apply", "applyDetached"],
    "MigrationRepository": ["apply", "rollback"],
    "CoexistenceRepository": ["provision", "cutover", "cleanup", "promote", "deactivate", "copyData"],
    "PatchRepository": ["apply"],
}


def _method(src: str, name: str) -> str:
    m = re.search(r"public function " + name + r"\((.*?)\n\t}", src, flags=re.S)
    assert m, f"{name} not found"
    return m.group(1)


def test_wing_hands_the_actor_to_bone():
    client = (WING / "Model/BoneClient.php").read_text(encoding="utf-8")
    assert "'X-Nos-Actor: '" in client, "BoneClient no longer sends X-Nos-Actor"
    for repo, methods in FORWARDS.items():
        src = (WING / f"Model/{repo}.php").read_text(encoding="utf-8")
        for name in methods:
            body = _method(src, name)
            assert re.search(r"\?string \$actor", body) and re.search(r"->post\([^;]*\$actor\s*,?\s*\)", body, re.S), (
                f"{repo}::{name} forwards to Bone without the actor")
    callers = list((WING / "Presenters").rglob("*Presenter.php"))
    calls = 0
    for f in callers:
        src = f.read_text(encoding="utf-8")
        for repo_prop, methods in (("upgrades", FORWARDS["UpgradeRepository"]),
                                   ("migrations", FORWARDS["MigrationRepository"]),
                                   ("coexistence", FORWARDS["CoexistenceRepository"]),
                                   ("patches", FORWARDS["PatchRepository"])):
            for name in methods:
                for call in re.findall(r"\$this->" + repo_prop + r"->" + name + r"\(([^;]*)\);", src):
                    calls += 1
                    assert re.search(r"Actor(Id)?\(\)\s*,?\s*\)?$", call.strip()), (
                        f"{f.name}: ->{repo_prop}->{name}({call}) passes no actor")
    assert calls >= 14, f"only {calls} forward calls found — the detector went blind"
