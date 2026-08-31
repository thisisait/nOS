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
#
# HERMES WAS MISSING until 2026-08-01, and its absence is the reason this map is
# now checked against the tree by test_the_daemon_map_covers_every_host_daemon
# below. A hand-written 2-entry map is a gate that only guards what its author
# happened to remember — the same shape as the defect it exists to catch.
HOST_DAEMONS = {
    "pazny.pulse": (("install pulse package", "sync pulse source"), "pulse"),
    "pazny.bone": (("sync bone source",), "bone"),
    "pazny.hermes": (("install hermes-agent",), "hermes"),
    "pazny.cortex": (("build dist-server",), "cortex"),
    "pazny.ears": (("sync listener source",), "ears"),
}

# Roles that bootstrap something into launchd but are NOT a long-lived process
# holding code in memory, with the reason. Each was surfaced by the coverage
# check below rather than remembered.
DAEMON_ROLES_EXCUSED = {
    "pazny.wing": "FrankenPHP serves from wing_app_dir; no installed-package step to miss, and the renders already notify",
    "pazny.backup": "launchd TIMER, not a daemon — each tick execs ~/.nos/backup.sh fresh, so no process can hold stale code",
    "pazny.backrest": "install_backrest defaults false and the role has no handlers file at all; wiring one is part of un-blocking that spike, not this gate",
    "pazny.linux.systemd_user": "shared helper role (ensure_unit.yml) invoked BY daemon roles — it owns no daemon of its own",
    # Surfaced by this check the day the reload was added (2026-08-09), and the
    # answer is that a notify would be WEAKER here, not merely different.
    #
    # A handler fires when ANSIBLE saw the change. The ollama keg is routinely
    # swapped by the operator at a shell — that is exactly how it moved from the
    # shadowing tap to core — and on the next converge brew reports changed=false,
    # so a notify-driven restart would never fire and the daemon would keep
    # executing the old binary. Measured within minutes of that swap:
    # `brew list --versions` said 0.32.6 while `ollama --version` said 0.30.7.
    #
    # So the role compares the RUNNING daemon against the INSTALLED keg and
    # reloads on the difference, whoever caused it. Same argument as the Wing
    # plist drift reload: key on reality, not on having just written something.
    "pazny.openclaw": "reloads on measured keg-vs-daemon drift, not on notify — "
                      "a handler misses the common case (operator swaps the keg "
                      "by hand, brew then reports changed=false forever)",
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


def test_a_notify_that_can_never_fire_is_not_a_restart():
    """The gate's own blind spot, closed 2026-08-01.

    `test_source_materialising_tasks_notify_a_restart` asserted a `notify` KEY
    existed. It does not follow that the notify can ever FIRE. pazny.pulse
    installed with `pip --quiet`, whose stdout is empty on every install and not
    just a no-op, under `changed_when: stdout | trim != ""` — so the condition
    was permanently false. Measured: the handler ran twice in the estate's whole
    history, last 2026-07-27 12:58:28, which is exactly the running daemon's
    start time; three later converges rewrote the package and the process kept
    executing 07-27 code. The gate was green throughout.

    A task is only credibly restart-wired if its changed signal comes from
    something other than the silenced output of its own command — OR the role
    carries a probe that observes the effect directly, which is the stronger
    fix because it also repairs drift that already happened.
    """
    offenders = []
    for role, (needles, _want) in HOST_DAEMONS.items():
        src = (REPO / "roles" / role / "tasks" / "main.yml").read_text()
        # An effect-probe reads the RUNNING process, not the installer's output.
        has_effect_probe = "ps -o lstart=" in src
        for t in _tasks(role):
            name = str(t.get("name", "")).lower()
            if not any(nd in name for nd in needles):
                continue
            cmd = str(t.get("ansible.builtin.command", t.get("ansible.builtin.shell", "")))
            changed = str(t.get("changed_when", ""))
            silenced = "--quiet" in cmd or " -q " in cmd
            reads_own_stdout = ".stdout" in changed
            if silenced and reads_own_stdout and not has_effect_probe:
                offenders.append(
                    f"{role}: task {t.get('name')!r} is run with --quiet but keys "
                    f"changed_when on its own stdout ({changed!r}) — always false, "
                    f"and the role has no probe that reads the running daemon"
                )
    assert not offenders, (
        "these notifies are structurally incapable of firing; the role needs a "
        "signal that OBSERVES THE EFFECT (is the running daemon older than its "
        "code?) rather than trusting the installer's account of itself:\n  "
        + "\n  ".join(offenders)
    )


def test_pulse_repairs_existing_drift_not_just_future_changes():
    """A change-triggered restart cannot fix a daemon that is ALREADY stale.

    Nothing changes on the converge that would need to repair it, so no event
    fires and the process runs old code forever. pazny.pulse must therefore
    carry a probe that compares the running daemon against the code on disk.
    """
    src = (REPO / "roles" / "pazny.pulse" / "tasks" / "main.yml").read_text()
    assert "ps -o lstart=" in src and "site-packages/pulse" in src, (
        "pazny.pulse has no staleness probe comparing the RUNNING daemon's start "
        "time against its installed code — without it, a daemon already running "
        "stale code is never repaired, only future changes are caught"
    )


def test_the_daemon_map_covers_every_host_daemon():
    """The map must be checked against the tree, not against memory.

    Hermes ran a launchd daemon and installed its source with
    `uv pip install -e .` and no notify for months; the map simply did not
    mention it, so the gate passed by not looking.
    """
    roles_dir = REPO / "roles"
    daemon_roles = set()
    for main in roles_dir.glob("pazny.*/tasks/main.yml"):
        text = main.read_text()
        # A host daemon = something this role bootstraps into launchd/systemd.
        if "launchctl bootstrap" in text or "systemd_user" in text:
            daemon_roles.add(main.parents[1].name)
    uncovered = sorted(daemon_roles - set(HOST_DAEMONS) - set(DAEMON_ROLES_EXCUSED))
    assert not uncovered, (
        "roles that bootstrap a host daemon but are absent from HOST_DAEMONS — "
        "a source change there restarts nothing and this gate never looks:\n  "
        + "\n  ".join(uncovered)
        + "\nAdd them, or excuse them in DAEMON_ROLES_EXCUSED with a reason."
    )


def test_the_notified_handlers_exist():
    """A notify naming a handler nobody defined is silently ignored by Ansible."""
    offenders = []
    for role in HOST_DAEMONS:
        hp = REPO / "roles" / role / "handlers" / "main.yml"
        # A notify resolves against a handler's NAME *or* its `listen:` topic —
        # collecting only names produced a false positive against pazny.cortex,
        # whose two platform handlers both `listen: Restart cortex`. Reading
        # half of Ansible's resolution rule makes the gate report a defect that
        # is not there, which costs exactly as much trust as missing one.
        defined = set()
        if hp.is_file():
            for h in (yaml.safe_load(hp.read_text()) or []):
                if not isinstance(h, dict):
                    continue
                if h.get("name"):
                    defined.add(h["name"])
                listen = h.get("listen")
                if isinstance(listen, str):
                    defined.add(listen)
                elif isinstance(listen, list):
                    defined.update(listen)
        for t in _tasks(role):
            for hook in _notifies(t):
                if hook not in defined:
                    offenders.append(f"{role}: notify {hook!r} has no handler ({sorted(defined)})")
    assert not offenders, "\n  ".join(["dangling notify targets:"] + offenders)
