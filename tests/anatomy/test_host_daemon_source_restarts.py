"""Anatomy gate — changing a host daemon's source must restart the daemon.

A host daemon (Bone, Pulse, Wing) runs from a copy of the repo materialised at
converge time. If the task that materialises that copy does not notify a restart
handler, the new code lands on disk and the RUNNING process keeps executing the
old code from memory. Nothing is red. The converge reports `changed`. The fix
simply does not take effect, and there is no signal at all.

MEASURED 2026-07-31, and this is not hypothetical:

  * `2704f4c4 fix(pulse): a job outliving one tick fired twice` shipped 07-28 and
    was correct — `_dispatch()` checks `_inflight_jobs`, sets it, and clears it.
  * The venv copy at ~/pulse/venv/.../pulse/daemon.py contained the fix.
  * The running daemon had been up since 07-27 12:58, i.e. from before it.
  * Four converges ran in between (07-28 … 07-31) and none restarted it.
  * So `conductor:vulnerability-scan` kept being dispatched twice a night —
    937s and 687s first runs, duplicates fired exactly 30s later, saved from
    concurrent execution only by the script's own PID lockfile. Which is
    precisely the failure the 07-28 commit message describes.

`roles/pazny.bone` already gets this right: its source-sync task notifies
`Restart bone`. `roles/pazny.pulse` notified the reload only from the PLIST
render — and the plist had not changed, so nothing fired.

CI-safe: YAML source scan. No Docker, no live host.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]

# role → (substrings identifying the task that materialises daemon source,
#         substring the notify must contain)
HOST_DAEMONS = {
    "pazny.pulse": (("install pulse package", "sync pulse source"), "pulse"),
    "pazny.bone": (("sync bone source",), "bone"),
}


def _tasks(role: str) -> list[dict]:
    p = REPO / "roles" / role / "tasks" / "main.yml"
    return [t for t in (yaml.safe_load(p.read_text()) or []) if isinstance(t, dict)]


def _notifies(task: dict) -> list[str]:
    n = task.get("notify")
    if n is None:
        return []
    return [n] if isinstance(n, str) else list(n)


def test_source_materialising_tasks_notify_a_restart():
    offenders = []
    for role, (needles, want) in HOST_DAEMONS.items():
        tasks = _tasks(role)
        assert tasks, f"{role}/tasks/main.yml parsed to nothing — path drift?"
        matched = [
            t for t in tasks
            if any(nd in str(t.get("name", "")).lower() for nd in needles)
        ]
        assert matched, (
            f"{role}: no task matched {needles} — the gate would silently pass. "
            f"Task names changed; update the needles."
        )
        for t in matched:
            hooks = [h for h in _notifies(t) if want in h.lower()]
            if not hooks:
                offenders.append(f"{role}: task {t.get('name')!r} materialises daemon source but notifies {_notifies(t) or 'nothing'}")

    assert not offenders, (
        "a host daemon's source can change without the daemon restarting — the "
        "new code lands on disk and the running process keeps the old code in "
        "memory, with no signal anywhere:\n  " + "\n  ".join(offenders)
    )


def test_the_notified_handlers_exist():
    """A notify naming a handler nobody defined is silently ignored by Ansible."""
    offenders = []
    for role in HOST_DAEMONS:
        hp = REPO / "roles" / role / "handlers" / "main.yml"
        defined = {
            h.get("name")
            for h in (yaml.safe_load(hp.read_text()) or [])
            if isinstance(h, dict)
        } if hp.is_file() else set()
        for t in _tasks(role):
            for hook in _notifies(t):
                if hook not in defined:
                    offenders.append(f"{role}: notify {hook!r} has no handler ({sorted(defined)})")
    assert not offenders, "\n  ".join(["dangling notify targets:"] + offenders)
