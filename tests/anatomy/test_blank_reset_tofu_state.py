"""Anatomy CI gate — blank-reset must reset OpenTofu Authentik working state.

When `blank=true` runs under the tofu engine, the Authentik DB is wiped, so every
provider/app/outpost gets a NEW pk on reinstall. But `terraform.tfstate` lives in
the REPO (not a data dir) and survives the blank — carrying STALE pks. The next
`tofu apply` then PUTs against pks that now belong to OTHER objects in the wiped
tenant → "provider with this name already exists" 400s, and the apply can clobber
the wrong object (high-impact data corruption). tasks/blank-reset.yml resets the
singular `terraform.tfstate` + `terraform.tfstate.backup` so tofu CREATEs cleanly.

The sibling gate `test_blank_reset_tofu_backups.py` pins the *timestamped*-backup
sweep. This gate pins the *integration contract* of the singular reset itself —
unguarded until now (test_tofu_authentik_conformance covers structure,
test_backup_restore_contract covers backup custody, neither pins blank):

  1. The reset task EXISTS in blank-reset.yml.
  2. It is SEQUENCED after LaunchAgent removal (§4) and before nginx reset (§5) —
     a refactor that moves it out of that window is caught.
  3. The `when:` gates on (authentik_engine|default('blueprint'))=='tofu' OR the
     legacy manage_authentik_with_tofu flag (never touches a blueprint tree).
  4. BOTH terraform.tfstate AND terraform.tfstate.backup are in the loop.
  5. The method is ansible.builtin.file + state:absent (idempotent, non-blocking
     on missing files — safe to run on any blank).
"""

from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
BLANK_RESET_PATH = REPO_ROOT / "tasks" / "blank-reset.yml"

RESET_NAME_FRAGMENT = "Reset OpenTofu Authentik state"
LAUNCHAGENT_REMOVE_FRAGMENT = "Remove LaunchAgent plists"
NGINX_RESET_FRAGMENT = "Remove nginx sites-enabled symlinks"


def _load_tasks() -> list[dict]:
    data = yaml.safe_load(BLANK_RESET_PATH.read_text())
    assert isinstance(data, list), "blank-reset.yml must be a task list"
    return data


def _task_name(task: dict) -> str:
    return str(task.get("name", ""))


def _index_of(tasks: list[dict], fragment: str) -> int:
    for i, t in enumerate(tasks):
        if fragment in _task_name(t):
            return i
    return -1


def _reset_task(tasks: list[dict]) -> dict:
    for t in tasks:
        if RESET_NAME_FRAGMENT in _task_name(t):
            return t
    raise AssertionError(
        "tofu state-reset task vanished from blank-reset.yml — a tofu-engine "
        "blank would carry stale pks and fail the next apply with 400 "
        "'provider with this name already exists'"
    )


def test_reset_task_exists():
    """The singular tofu state-reset task must be present."""
    _reset_task(_load_tasks())  # raises with a clear message if absent


def test_reset_sequenced_between_launchagents_and_nginx():
    """The reset must live between LaunchAgent removal (§4) and nginx reset (§5).

    It must run AFTER the Docker/Authentik teardown so the DB is already wiped,
    and BEFORE the playbook starts reconverging — a refactor that drifts it out
    of that window is a regression this gate catches.
    """
    tasks = _load_tasks()
    reset_idx = _index_of(tasks, RESET_NAME_FRAGMENT)
    launch_idx = _index_of(tasks, LAUNCHAGENT_REMOVE_FRAGMENT)
    nginx_idx = _index_of(tasks, NGINX_RESET_FRAGMENT)

    assert reset_idx != -1, "tofu state-reset task missing"
    assert launch_idx != -1, "LaunchAgent removal anchor missing — file refactored"
    assert nginx_idx != -1, "nginx reset anchor missing — file refactored"

    assert launch_idx < reset_idx < nginx_idx, (
        "tofu state-reset is out of sequence: it must run after LaunchAgent "
        f"removal (idx {launch_idx}) and before nginx reset (idx {nginx_idx}), "
        f"but sits at idx {reset_idx}"
    )


def test_when_gates_on_tofu_engine_or_legacy_flag():
    """The reset must gate on the tofu engine OR the legacy tofu flag.

    Both the current `authentik_engine == 'tofu'` selector AND the legacy
    `manage_authentik_with_tofu` flag must appear, so neither a fresh tofu
    install nor a legacy-flag install leaks stale state — and a blueprint-engine
    tree is never touched.
    """
    when = str(_reset_task(_load_tasks()).get("when", ""))
    assert "authentik_engine" in when, (
        "reset `when:` no longer references authentik_engine — a fresh "
        "tofu-engine blank would skip the reset"
    )
    assert "'tofu'" in when or '"tofu"' in when, (
        "reset `when:` no longer compares authentik_engine against 'tofu'"
    )
    assert "manage_authentik_with_tofu" in when, (
        "reset `when:` dropped the legacy manage_authentik_with_tofu flag — "
        "legacy-flag installs would skip the reset"
    )


def test_loop_covers_both_state_files():
    """Both terraform.tfstate AND terraform.tfstate.backup must be wiped."""
    loop = _reset_task(_load_tasks()).get("loop", [])
    assert isinstance(loop, list), "reset task must loop over an explicit file list"
    assert "terraform.tfstate" in loop, "terraform.tfstate not wiped on blank"
    assert "terraform.tfstate.backup" in loop, (
        "terraform.tfstate.backup not wiped on blank — stale pk snapshot survives"
    )


def test_method_is_file_absent():
    """The reset must use ansible.builtin.file state:absent (idempotent, safe).

    state:absent is non-blocking on missing files (a blueprint-engine tree, or a
    first-ever blank, simply has no tfstate) — so the task can never hard-fail a
    blank. A shell `rm` or a different module would lose that safety.
    """
    reset = _reset_task(_load_tasks())
    assert "ansible.builtin.file" in reset, (
        "reset no longer uses ansible.builtin.file — lost idempotent, "
        "missing-file-safe deletion semantics"
    )
    fmod = reset["ansible.builtin.file"]
    assert fmod.get("state") == "absent", (
        "reset file module is not state:absent — it would not delete the tfstate"
    )
    # The path must target the tofu authentik working dir, parameterized by item.
    path = str(fmod.get("path", ""))
    assert "terraform/authentik" in path, (
        "reset path no longer targets terraform/authentik — wrong state dir"
    )
    assert "{{ item }}" in path, (
        "reset path no longer interpolates the loop item — only one file wiped"
    )
