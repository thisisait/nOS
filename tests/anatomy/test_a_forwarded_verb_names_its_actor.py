"""A verb Wing forwards to Bone names the person who decided it.

WHY (roadmap `wing-tier-followups` item 4, measured 2026-10-07). Wing gates
apply / rollback / cutover / cleanup / provision / patch apply on wing.operator
and knows the person (user:<uid>), then called Bone with its own client bearer
and nothing else: the person stopped at Wing. Now BoneClient sends X-Nos-Actor,
Bone's middleware holds it for the request, and invoke_playbook (which every
mutating verb runs through) hands it to the run as nos_actor and names it in
the reply.

What runs: Bone's real main.py app over TestClient, JWT verification stubbed,
ansible-playbook replaced by a recorder. Nothing leaves the process.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

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
    monkeypatch.setattr(sys.modules["auth"], "verify_token", lambda token, required_scopes=(): {"sub": "nos-wing"})

    runs: list[list[str]] = []

    class Proc:
        returncode = 0

        def __init__(self, cmd, **_):
            runs.append(cmd)

        def communicate(self, timeout=None):  # noqa: ARG002
            return "ok", None

    monkeypatch.setattr(sys.modules["migrations"].subprocess, "Popen", Proc)
    return TestClient(main.app), runs


def _apply(client, **headers):
    return client.post("/api/patches/PATCH-001/apply", headers={"Authorization": "Bearer t", **headers})


def test_the_run_and_the_reply_name_the_person(bone):
    client, runs = bone
    r = _apply(client, **{"X-Nos-Actor": "user:alice"})
    assert r.status_code == 200, r.text
    assert r.json()["actor"] == "user:alice"
    assert "nos_actor=user:alice" in runs[-1][runs[-1].index("--extra-vars") + 1]


def test_no_header_names_nobody_and_a_forged_one_is_refused(bone):
    client, runs = bone
    r = _apply(client)
    assert r.status_code == 200 and r.json()["actor"] is None, r.text
    assert "nos_actor" not in " ".join(runs[-1])
    n = len(runs)
    assert _apply(client, **{"X-Nos-Actor": "user:a b --tags all"}).status_code == 400
    assert len(runs) == n, "a refused actor still ran the playbook"


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
