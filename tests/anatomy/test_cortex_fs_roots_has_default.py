"""A fs-gated fact used outside its guard must carry a default.

`_cortex_fs_user_roots` is set_fact only `when: cortex_fs_enabled`, but the
daemon env references it UNCONDITIONALLY — the systemd-user env dict
(tasks/main.yml) and the launchd plist (cortex.plist.j2). On an fs-disabled
host (the Linux default) the fact is never defined, so the reference raises
'_cortex_fs_user_roots is undefined' and the converge dies before the daemon
ever starts. Found in the 2026-09-04 KEAP×nOS grand review; the Linux wet-test
did not catch it, so this pins the shape: every use outside the guarded
set_fact carries `| default`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FILES = [
    REPO / "roles/pazny.cortex/tasks/main.yml",
    REPO / "roles/pazny.cortex/templates/cortex.plist.j2",
]
VAR = "_cortex_fs_user_roots"


def test_every_unguarded_use_has_a_default():
    offenders = []
    for f in FILES:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if VAR not in line:
                continue
            # The set_fact DEFINITION is the assignment, not a `{{ }}` read.
            if re.search(rf"^\s*{VAR}\s*:", line):
                continue
            if "{{" in line and "| default" not in line:
                offenders.append(f"{f.relative_to(REPO)}:{i}")
    assert not offenders, (
        f"{VAR} is read without `| default` at {offenders}; it is set only when "
        "cortex_fs_enabled, so an fs-disabled converge crashes on the undefined var"
    )
