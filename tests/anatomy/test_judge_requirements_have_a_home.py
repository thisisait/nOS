"""A judge's declared credential requirement must have a home in Bone's env.

Judges run as subprocesses of the BONE daemon (looproutes._execute →
judges.run_gate_set), so `default_requirement_probe` reads BONE's environment
— not wing.plist, not a Pulse job env, not ~/.nos/secrets.yml. The first bound
ceremony (2026-08-29, judge run 389d0e6c) skipped cortex-corpus-diff as
"requirement(s) absent" while both tokens sat persisted in secrets.yml and one
of them in wing.plist: credentials existed everywhere except the one process
that runs the judge.

Three claims, each read off the artifact:

  1. Every `requires:` name in state/judge-sets.yml is one the probe KNOWS —
     deny-by-default means an unknown name is a judge that is silently
     INDETERMINATE forever.
  2. Every env var in judges.REQUIREMENT_ENV is declared as a <key> in
     roles/pazny.bone/templates/bone.plist.j2 — the env the engine actually
     inherits.
  3. The probe itself answers from the environment (run, not grepped).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
JUDGES_PY = ROOT / "files" / "anatomy" / "bone" / "judges.py"
REGISTRY = ROOT / "state" / "judge-sets.yml"
BONE_PLIST = ROOT / "roles" / "pazny.bone" / "templates" / "bone.plist.j2"

# The two non-credential requirements the probe implements with its own
# branches (docker presence, live container runtime). Not env-backed.
NON_ENV_REQUIREMENTS = {"docker", "live_estate"}


def _judges():
    spec = importlib.util.spec_from_file_location("nos_bone_judges", str(JUDGES_PY))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nos_bone_judges"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_every_declared_requirement_is_one_the_probe_knows():
    judges = _judges()
    known = set(judges.REQUIREMENT_ENV) | NON_ENV_REQUIREMENTS
    registry = yaml.safe_load(REGISTRY.read_text())
    for name, body in registry["judges"].items():
        for req in body.get("requires") or []:
            assert req in known, (
                f"judge {name!r} requires {req!r}, which "
                f"default_requirement_probe does not know — deny-by-default "
                f"makes this judge INDETERMINATE forever, silently"
            )


def test_every_requirement_env_var_is_in_bone_launchd_env():
    judges = _judges()
    plist = BONE_PLIST.read_text()
    for req, env_name in judges.REQUIREMENT_ENV.items():
        assert f"<key>{env_name}</key>" in plist, (
            f"requirement {req!r} is satisfied only by ${env_name} in the "
            f"BONE daemon's environment, and bone.plist.j2 does not declare "
            f"it — the judge will be skipped as 'requirement(s) absent' on "
            f"every run (the 2026-08-29 first-bound-ceremony shape)"
        )


def test_the_probe_reads_the_environment(monkeypatch):
    judges = _judges()
    for req, env_name in judges.REQUIREMENT_ENV.items():
        monkeypatch.delenv(env_name, raising=False)
        assert judges.default_requirement_probe(req) is False
        monkeypatch.setenv(env_name, "  ")
        assert judges.default_requirement_probe(req) is False, "whitespace is not a credential"
        monkeypatch.setenv(env_name, "tok")
        assert judges.default_requirement_probe(req) is True
    assert judges.default_requirement_probe("no-such-requirement") is False
