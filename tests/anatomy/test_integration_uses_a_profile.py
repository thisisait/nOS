"""The required Linux install test converges a shipped profile, not a CI-only service set.

It converged tests/config.yml plus an ad-hoc -e blob, a set nobody ships (ruling 2026-10-15).
tests/config.yml stays as the runner's host settings; each install_* override is named below.
"""
from __future__ import annotations

import json
import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CI = REPO / ".github" / "workflows" / "ci.yml"
PROFILE = "profiles/core.yml"

# Each override is a platform fact or a ruling, never a convenience.
ALLOWED_OVERRIDES = {
    "install_thalamus": "pazny.thalamus fails on systemd hosts (macOS-only in slice 1)",
    "install_cortex": "operator 2026-10-01: KEAP + cortex ride the Linux leg",
}


def _converges() -> list[str]:
    job = yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]["integration-linux"]
    return [str(s["run"]) for s in job["steps"]
            if "ansible-playbook main.yml" in str(s.get("run", ""))
            and "--syntax-check" not in str(s["run"])]


def _overridden_flags(run: str) -> set[str]:
    flags = set(re.findall(r"-e\s+['\"]?(install_\w+)=", run))
    for blob in re.findall(r"-e\s+'(\{.*?\})'", run):
        flags |= {k for k in json.loads(blob) if k.startswith("install_")}
    return flags


def test_flag_reader() -> None:
    assert _overridden_flags("-e install_a=true -e '{\"install_b\": 1, \"x\": 2}'") == {
        "install_a", "install_b"}


def test_linux_install_converges_the_core_profile() -> None:
    assert (REPO / PROFILE).is_file(), f"{PROFILE} is gone"
    runs = _converges()
    assert runs, "integration-linux has no converge step"
    missing = [r.split("\n")[0] for r in runs if f"-e @{PROFILE}" not in r]
    assert not missing, f"a Linux converge does not pass -e @{PROFILE}: {missing}"


def test_linux_install_overrides_only_named_flags() -> None:
    extra = set().union(*map(_overridden_flags, _converges())) - set(ALLOWED_OVERRIDES)
    assert not extra, (
        f"integration-linux overrides {sorted(extra)} on top of {PROFILE}; set it in the "
        "profile, or add it to ALLOWED_OVERRIDES with the platform fact or ruling behind it")
