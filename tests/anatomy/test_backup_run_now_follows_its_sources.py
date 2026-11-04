"""Gate: backup_run_now runs after every role that creates a dir it backs up.

2026-10-30 blank: run-now fired inside pazny.backup (main.yml task ~120), before
pazny.thalamus created medulla_data_dir (~130); medulla is empty_ok, so the first
backup silently left the medulla's settings out. Parsed from main.yml.
"""
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

RUNNERS = ("ansible.builtin.command", "ansible.builtin.shell", "command", "shell")


def _role_ref(task):
    for key in ("ansible.builtin.import_role", "ansible.builtin.include_role", "import_role", "include_role"):
        if isinstance(task.get(key), dict):
            return task[key]
    return None


def _source_flags():
    return {d["flag"] for d in ni.default_config()["backup_dirs_to_dump"] if d.get("flag")}


def _runs_backup_script(tasks):
    for t in tasks or []:
        if any(_runs_backup_script(t.get(k)) for k in ("block", "rescue", "always")):
            return True
        for mod in RUNNERS:
            v = t.get(mod)
            if "backup_script_path" in str(v.get("cmd", "") if isinstance(v, dict) else v or ""):
                return True
    return False


def test_run_now_comes_after_every_role_a_backup_dir_depends_on():
    tasks = yaml.safe_load((REPO / "main.yml").read_text())[0]["tasks"]
    run_now = [i for i, t in enumerate(tasks)
               if (_role_ref(t) or {}).get("name") == "pazny.backup"
               and (_role_ref(t) or {}).get("tasks_from") == "run-now"]
    assert len(run_now) == 1, "main.yml must call pazny.backup tasks_from run-now exactly once"
    # The role's own main.yml must not run backup.sh at its import position.
    role_main = yaml.safe_load((REPO / "roles/pazny.backup/tasks/main.yml").read_text())
    assert not _runs_backup_script(role_main), "a task in pazny.backup main.yml still runs backup.sh"

    flags = _source_flags()
    # ponytail: top-level tasks only; a source role buried in an included file is not seen.
    later = [t.get("name") for t in tasks[run_now[0] + 1:]
             if _role_ref(t) and any(f in yaml.safe_dump(t.get("when", "")) for f in flags)]
    assert not later, f"roles creating backup sources run after backup_run_now: {later}"
