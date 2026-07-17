"""Anatomy gate — external-volume mount preflight wiring (shipped 2026-07-17).

WHY: when nos_data_root is redirected onto an external /Volumes disk, Docker
Desktop's Linux VM can hold a STALE /host_mnt reference (disk remounted after
Docker started). Every bind-mount then fails at container-create, containers sit
in `Created`, and the STRICT health-wait hangs the WHOLE run for the full
stack_up_wait_timeout with no diagnosis (observed 2026-07-17: infra frozen at
3/11 for 59 ticks). `tasks/stacks/docker-external-mount-preflight.yml` probes the
mount in ~5s BEFORE the first `docker compose up` and either self-heals (blank /
docker_autoheal_external_mount) or fails fast with the exact remedy.

This offline gate pins the wiring so it can't silently regress:
  1. the preflight task file exists + is valid YAML;
  2. core-up.yml includes it via include_tasks;
  3. the include runs BEFORE the "Start INFRA stack" compose-up (else the probe
     is useless — it must precede the first up -d);
  4. the self-heal auto-restart is gated on blank OR docker_autoheal_external_mount
     (never a surprise Docker restart under a live operator's containers);
  5. docker_autoheal_external_mount + docker_mount_probe_image are REAL keys in
     default.config.yml (global, not role-default-only, so the loader/eager
     `{{ vars }}` resolution + every task sees them).

No network, no docker, fast.
"""
from __future__ import annotations

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PREFLIGHT = REPO_ROOT / "tasks" / "stacks" / "docker-external-mount-preflight.yml"
CORE_UP = REPO_ROOT / "tasks" / "stacks" / "core-up.yml"
CONFIG = REPO_ROOT / "default.config.yml"


def _load_tasks(path: pathlib.Path) -> list:
    docs = list(yaml.safe_load_all(path.read_text()))
    # A task file is a single YAML document holding a list of task dicts.
    tasks = docs[0] if docs else None
    assert isinstance(tasks, list), f"{path} did not parse to a task list"
    return tasks


def _flatten_when(when) -> str:
    """Render a task's `when:` (str or list of str) into one searchable string."""
    if when is None:
        return ""
    if isinstance(when, list):
        return " && ".join(str(w) for w in when)
    return str(when)


# ── 1. preflight file exists + valid YAML ─────────────────────────────────────
def test_preflight_file_exists_and_parses():
    assert PREFLIGHT.is_file(), f"missing preflight task file: {PREFLIGHT}"
    tasks = _load_tasks(PREFLIGHT)
    assert tasks, "preflight task file has no tasks"


# ── 2. core-up.yml includes it via include_tasks ──────────────────────────────
def _find_preflight_include(core_tasks: list) -> int:
    for i, t in enumerate(core_tasks):
        if not isinstance(t, dict):
            continue
        inc = t.get("include_tasks") or t.get("ansible.builtin.include_tasks")
        if isinstance(inc, str) and inc.strip() == "docker-external-mount-preflight.yml":
            return i
        if isinstance(inc, dict) and inc.get("file", "").strip() == "docker-external-mount-preflight.yml":
            return i
    return -1


def test_core_up_includes_preflight():
    idx = _find_preflight_include(_load_tasks(CORE_UP))
    assert idx >= 0, (
        "core-up.yml does not include docker-external-mount-preflight.yml via include_tasks"
    )


# ── 3. ordering: preflight include is BEFORE the INFRA compose-up ─────────────
def _find_infra_up(core_tasks: list) -> int:
    for i, t in enumerate(core_tasks):
        if not isinstance(t, dict):
            continue
        cmd = t.get("shell") or t.get("ansible.builtin.shell") or ""
        cmd = cmd if isinstance(cmd, str) else str(cmd)
        name = str(t.get("name", ""))
        # The infra bring-up is the compose `up -d` in the task named "Start INFRA stack".
        if "Start INFRA stack" in name and "up -d" in cmd:
            return i
    return -1


def test_preflight_runs_before_infra_up():
    core_tasks = _load_tasks(CORE_UP)
    pre = _find_preflight_include(core_tasks)
    infra = _find_infra_up(core_tasks)
    assert pre >= 0, "preflight include not found in core-up.yml"
    assert infra >= 0, "'Start INFRA stack' compose up -d task not found in core-up.yml"
    assert pre < infra, (
        f"external-mount preflight (task #{pre}) must run BEFORE the INFRA compose "
        f"up -d (task #{infra}); otherwise the probe fires too late to prevent the "
        "20-min stuck-`Created` health-wait hang."
    )


# ── 4. self-heal auto-restart gated on blank OR docker_autoheal_external_mount ─
def _find_self_heal_block(tasks: list) -> dict | None:
    """Recurse through nested `block:` groups to find the self-heal restart block."""
    for t in tasks:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name", ""))
        # The self-heal is the task carrying an inner `block:` whose name mentions Self-heal.
        if "block" in t and ("Self-heal" in name or "restart docker" in name.lower()):
            return t
        # Descend into any nested block to reach it (the self-heal block is nested
        # inside the outer "External-mount preflight" block).
        if isinstance(t.get("block"), list):
            found = _find_self_heal_block(t["block"])
            if found is not None:
                return found
    return None


def test_self_heal_gated_on_blank_and_autoheal_flag():
    tasks = _load_tasks(PREFLIGHT)
    block = _find_self_heal_block(tasks)
    assert block is not None, "self-heal `block:` (restart Docker Desktop) not found in preflight"
    when = _flatten_when(block.get("when"))
    assert "blank" in when, (
        f"self-heal `when:` must reference `blank` (blank run auto-heals). Got: {when!r}"
    )
    assert "docker_autoheal_external_mount" in when, (
        "self-heal `when:` must reference `docker_autoheal_external_mount` (the opt-in "
        f"flag for a live non-blank system). Got: {when!r}"
    )


# ── 5. config keys are REAL global keys in default.config.yml ─────────────────
def test_config_keys_are_global():
    cfg = yaml.safe_load(CONFIG.read_text())
    assert isinstance(cfg, dict), "default.config.yml did not parse to a mapping"
    assert "docker_autoheal_external_mount" in cfg, (
        "docker_autoheal_external_mount must be a global key in default.config.yml"
    )
    assert cfg["docker_autoheal_external_mount"] is False, (
        "docker_autoheal_external_mount default must be false (no surprise restarts)"
    )
    assert "docker_mount_probe_image" in cfg, (
        "docker_mount_probe_image must be a global key in default.config.yml"
    )
    assert cfg["docker_mount_probe_image"] == "alpine:3", (
        f"docker_mount_probe_image default expected 'alpine:3', got {cfg['docker_mount_probe_image']!r}"
    )
