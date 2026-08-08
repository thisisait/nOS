"""launchd does not re-read a plist it has already loaded.

WHAT HAPPENED, 2026-08-08, found by the first end-to-end run of the agent inbox.

A converge rendered `WING_PUBLIC_URL` into Wing's launchd plist so a question
notification could carry a `Click` link to /inbox. The playbook was green, the
daemon restarted (`runs = 3`), and:

    $ grep -c WING_PUBLIC_URL ~/Library/LaunchAgents/eu.thisisait.nos.wing.plist
    2
    $ launchctl print gui/501/eu.thisisait.nos.wing | grep -c WING_PUBLIC_URL
    0

The file had it. The process did not. `click_url` came out NULL on a real
notification and the phone got an alert with no link.

`launchctl kickstart -k` restarts the PROCESS and reuses the job definition
launchd already holds in memory. Only `bootout` + `bootstrap` re-reads the file.
The comment above Wing's bootstrap task said "kickstart -k for graceful restart
on plist change" — precisely the thing kickstart does not do.

WHY IT MATTERS BEYOND ONE LINK. Every host-daemon secret and setting lives in
these plists: `WING_EVENTS_HMAC_SECRET`, `AUTHENTIK_BOOTSTRAP_TOKEN`,
`INFISICAL_API_TOKEN`, `NOS_REPO_ROOT`. Any of them, changed or rotated, took
effect at the next REBOOT and not before — silently, with a green playbook. It
is the same defect as ntfy's config that morning (rendered, never read), one
layer up, and it is why the estate spent an unknown period with Bone verifying
HMACs against a retired key.

Bone's variant was worse: a loaded job took NO action at all — not even a
restart. It survived the secret desync only because Bone self-heals that one
variable in-process. Nothing else it reads from its plist would have updated.

WHAT THIS PINS: all three host daemons must bootout+bootstrap when their plist
CHANGED, and must therefore register the render task to know that it did.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: role -> (plist template name, the register var its bootstrap must consult)
DAEMONS = {
    "pazny.wing": ("wing.plist.j2", "_wing_plist"),
    "pazny.bone": ("bone.plist.j2", "_bone_plist"),
    "pazny.pulse": ("pulse.plist.j2", "_pulse_plist"),
}


def tasks_src(role: str) -> str:
    return (REPO / "roles" / role / "tasks/main.yml").read_text(encoding="utf-8")


def bootstrap_task(role: str) -> str:
    """The launchd bootstrap task, verbatim.

    ONE finder, used by every test here. The first version duplicated the
    slicing logic in two tests and got it wrong in both the same way — fixing
    one left the other failing against correct code.
    """
    src = tasks_src(role)
    m = re.search(r"^- name: .*Bootstrap launchd job.*$", src, re.M)
    assert m, f"{role}: no launchd bootstrap task"
    end = src.find("\n- name:", m.end())
    block = src[m.start() : end if end != -1 else len(src)]
    assert len(block) > 200, (
        f"{role}: the bootstrap block is implausibly short ({len(block)} chars) "
        "— the anchor is wrong, not the code."
    )
    return block


def bootstrap_block(role: str) -> str:
    """The shell body of the launchd bootstrap task, comments stripped.

    Comments are removed because this gate asks what the SHELL does, and the
    blocks deliberately explain the defect they fix — a gate matching prose
    would fail on its own documentation, which happened five times while this
    feature was built.
    """
    return re.sub(r"^\s*#.*$", "", bootstrap_task(role), flags=re.M)


@pytest.mark.parametrize("role", sorted(DAEMONS))
def test_the_plist_render_is_registered(role: str):
    """The bootstrap cannot react to a change it was never told about."""
    template, reg = DAEMONS[role]
    src = tasks_src(role)
    idx = src.find(f"src: {template}")
    assert idx != -1, f"{role}: no task renders {template}"
    # The register must belong to the render task: look back to its `- name:`.
    task_start = src.rfind("- name:", 0, idx)
    assert f"register: {reg}" in src[task_start:idx], (
        f"{role}: the task rendering {template} does not `register: {reg}`, so "
        "the bootstrap below cannot know the plist changed and will reuse the "
        "job definition launchd already holds."
    )


@pytest.mark.parametrize("role", sorted(DAEMONS))
def test_a_changed_plist_is_booted_out_and_back_in(role: str):
    """kickstart is not a reload; bootout+bootstrap is."""
    _, reg = DAEMONS[role]
    block = bootstrap_block(role)
    assert reg in block, (
        f"{role}: the bootstrap does not consult {reg}. It cannot distinguish "
        "'plist changed' from 'steady state', which is the whole point."
    )
    assert "bootout" in block, (
        f"{role}: the bootstrap never calls `launchctl bootout`. Without it a "
        "loaded job keeps its in-memory EnvironmentVariables and a rendered "
        "change reaches the process only at the next reboot."
    )
    # bootout must be followed by a bootstrap, or the daemon simply stops.
    after = block[block.find("bootout"):]
    assert "bootstrap" in after, (
        f"{role}: `bootout` with no following `bootstrap` — that unloads the "
        "daemon and leaves it down."
    )


@pytest.mark.parametrize("role", sorted(DAEMONS))
def test_a_reload_reports_itself_as_changed(role: str):
    """A reload that reports changed=0 is a converge lying about its own work."""
    block = bootstrap_block(role)
    assert "reloaded" in block, (
        f"{role}: the bootstrap does not emit a distinct 'reloaded' signal, so "
        "its changed_when cannot tell a reload from a no-op."
    )
    task = bootstrap_task(role)
    assert "reloaded" in task[task.find("changed_when"):], (
        f"{role}: `changed_when` ignores the reload signal, so re-loading a "
        "daemon with new credentials reports changed=0."
    )
