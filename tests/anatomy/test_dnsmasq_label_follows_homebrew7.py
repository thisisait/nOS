"""The dnsmasq LaunchDaemon plist is found under Homebrew 7's naming too.

Homebrew 7 ships formula service plists as ``sh.brew.<svc>.plist``; earlier
releases used ``homebrew.mxcl.<svc>.plist``. ``dnsmasq_launchd_label`` was a
fixed ``homebrew.mxcl.dnsmasq``, so on a fresh Homebrew 7 Mac "[dnsmasq]
Install the dnsmasq system LaunchDaemon plist" failed with "Source
…/opt/dnsmasq/homebrew.mxcl.dnsmasq.plist not found" (thisisait/nOS#46).

Before the plist is copied, tasks/dnsmasq.yml must resolve the label against
what the formula actually shipped, falling back to ``sh.brew.dnsmasq``.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TASKS = REPO / "tasks/dnsmasq.yml"
COPY_NAME = "[dnsmasq] Install the dnsmasq system LaunchDaemon plist"


def test_label_is_resolved_against_brew7_naming_before_the_copy():
    tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8")) or []
    names = [t.get("name") for t in tasks]
    assert COPY_NAME in names, "gate went blind: plist copy task renamed or gone"
    before = tasks[: names.index(COPY_NAME)]

    resolves = [
        t for t in before
        if "dnsmasq_launchd_label" in (t.get("ansible.builtin.set_fact") or t.get("set_fact") or {})
        and "sh.brew.dnsmasq" in yaml.safe_dump(t)
    ]
    assert resolves, (
        "no task before the plist copy re-points dnsmasq_launchd_label at "
        "sh.brew.dnsmasq when Homebrew 7 shipped that instead"
    )
