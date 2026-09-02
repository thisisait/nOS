"""Anatomy CI gate — the blueprint re-apply runs as a uid that can read 0600.

MEASURED on run 33660558975 (2026-09-02): SEC-1 renders every plugin file 0600
owned by the ansible user; on Linux the container's uid-1000 gets EACCES on the
bind mount and `ak apply_blueprint` fails — swallowed by `|| true` since
2026-05-23. Authentik held ZERO applications and every forward-auth route
served the outpost's own 404. macOS VirtioFS masks ownership, so the estate
never saw it. The exec runs `-u root`; the boot scan stays unprivileged; the
verify task (tasks/verify-authentik-apps.yml) reads the result back.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_both_reapply_handlers_exec_as_root():
    for f in ("roles/pazny.authentik/handlers/main.yml", "main.yml"):
        src = (REPO / f).read_text(encoding="utf-8")
        applies = re.findall(
            r"compose -p infra exec ([^\n]*?)authentik-worker \\\n\s*ak apply_blueprint",
            src)
        assert applies, f"{f}: no apply_blueprint exec found; re-read this gate"
        for flags in applies:
            assert "-u root" in flags, (
                f"{f}: apply_blueprint execs as the container user, which "
                "cannot read a 0600 host-owned bind on Linux — the apply fails "
                "and `|| true` hides it (run 33660558975: zero applications)")
