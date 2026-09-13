"""The Homebrew App-source skip is for retired tokens only.

A global failed_when on ``It seems the App source`` made every cask in
``homebrew_cask_apps`` succeed after a non-zero brew when Homebrew printed
that line — not just ``windsurf`` after the Devin rebrand.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
TASK = REPO / "roles/pazny.mac.homebrew/tasks/main.yml"
CFG = REPO / "default.config.yml"


def test_app_source_exemption_is_keyed_to_upgrade_ignore():
    src = TASK.read_text(encoding="utf-8")
    marker = "It seems the App source"
    assert marker in src
    # Same failed_when block as the install loop, not a free-floating skip.
    i = src.index(marker)
    window = src[max(0, i - 1200) : i + 80]
    assert "homebrew_cask_upgrade_ignore" in window, (
        "App-source skip must be gated on homebrew_cask_upgrade_ignore, "
        "not a play-wide stdout match"
    )
    # The old global form: failed_when item that only tests stdout membership.
    assert "'It seems the App source' not in _cask_result.stdout" not in src


def test_windsurf_is_the_retired_token():
    cfg = CFG.read_text(encoding="utf-8")
    assert "homebrew_cask_upgrade_ignore:" in cfg
    assert "windsurf" in cfg
    assert "devin-desktop" in cfg
