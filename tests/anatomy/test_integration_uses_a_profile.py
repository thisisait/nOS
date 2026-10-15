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



def _load(rel: str) -> dict:
    return yaml.safe_load((REPO / rel).read_text(encoding="utf-8")) or {}


def _linux_host_organs() -> set[str]:
    """install_flag of each host row (no `stack:`) whose main.yml role is not Darwin-only."""
    rows = yaml.safe_load((REPO / "state/manifest.yml").read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else next(v for v in rows.values() if isinstance(v, list))
    play = yaml.safe_load((REPO / "main.yml").read_text(encoding="utf-8"))[0]
    darwin_only = {
        (t.get("ansible.builtin.import_role") or t.get("ansible.builtin.include_role") or {}).get("name")
        for sect in ("pre_tasks", "tasks", "post_tasks") for t in play.get(sect) or []
        if "Darwin" in str(t.get("when", ""))}
    return {r["install_flag"] for r in rows
            if r.get("stack") is None and f"pazny.{r['id']}" not in darwin_only}


def test_linux_install_keeps_the_host_organs() -> None:
    # Bonus lanes skip host rows, so this converge is their only blocking lane: an organ the
    # old run (tests/config.yml over defaults) converged must stay on. Precedence: blob > profile > config.
    base = {k: v for f in sorted(REPO.glob("config.d/*.yml")) for k, v in _load(str(f)).items()}
    base.update({**_load("default.config.yml"), **_load("tests/config.yml")})
    now = {**base, **_load(PROFILE)}
    for run in _converges():
        for blob in re.findall(r"-e\s+'(\{.*?\})'", run):
            now.update(json.loads(blob))
    lost = sorted(f for f in _linux_host_organs() if base.get(f) is True and now.get(f) is not True)
    assert not lost, f"integration-linux no longer converges host organs {lost}; turn them on there"
