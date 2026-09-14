"""GitLab host-bind dirs are not nightly sources when the service is off.

MEASURED 2026-09-14: install_gitlab is false, leftover
``/Volumes/SSD1TB/.../gitlab/data`` still exists, ``-d`` passes, alpine tar
rc=1, backup-status.json records dir-gitlab FAILED, A9 HIGH every night.

Absent is FAILED (unmounted SSD). Disabled-and-left-behind is not a live
source. The render skips those names when install_gitlab is off.

YAML/Jinja only — CI does not run backup.sh.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "roles" / "pazny.backup" / "files" / "backup.sh"


def test_gitlab_dirs_are_gated_on_the_install_flag():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "install_gitlab" in text, (
        "backup.sh still dumps gitlab* even when install_gitlab is off — "
        "leftover datadir HIGH-fails the night (2026-09-14)"
    )
    assert "gitlab-config" in text
    assert "DIR_NAMES=" in text
    # The skip is in the same for-loop that emits the names, not a later comment.
    names_line = next(ln for ln in text.splitlines() if ln.startswith("DIR_NAMES="))
    assert "install_gitlab" in names_line
    paths_line = next(ln for ln in text.splitlines() if ln.startswith("DIR_PATHS="))
    assert "install_gitlab" in paths_line
