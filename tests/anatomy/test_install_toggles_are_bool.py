"""Anatomy gate — an install_* toggle in a condition is filtered through bool.

THE SYMPTOM (2026-10-21, spark1). `-e install_cortex=true` arrives as the
string "true"; main.yml's `when: install_cortex | default(false)` handed that
string to a conditional and ansible-core refused the play (strings are no
longer truthy there). 142 one-line `when:` reads had no `| bool`.

THE FIX. Every `install_<x> | default(...)` in a `when:` line of a playbook or
task file is followed by `| bool`, so a toggle from extra-vars, config.yml or a
profile means the same thing.

An inline task (`- { name: ..., when: ... }`) is left bare: test_config_stock_jinja_only
forbids a non-stock filter there, and so on a line marked `# stock-Jinja` (meta: when:);
a string extra-var still breaks those lines.

CEILING. One-line `when:` only (a list under `when:` is not read), and only the
`install_x | default(...)` spelling. Jinja values and state/*.yml (read by the
tools' own evaluator) are out of scope: there a string does not crash the play.
"""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BARE = re.compile(r"\binstall_[a-z0-9_]+ \| default\((?:true|false)\)(?! \| bool)")


def test_every_install_toggle_read_is_a_bool():
    files = [f for f in subprocess.run(["git", "ls-files", "*.yml"], cwd=REPO, capture_output=True,
                                       text=True, check=True).stdout.split()
             if f == "main.yml" or f.startswith("tasks/") or "/tasks/" in f or "/handlers/" in f]
    bare = [f"{f}:{n}" for f in files for n, line in enumerate(
        (REPO / f).read_text(encoding="utf-8", errors="replace").splitlines(), 1)
        if "when:" in line and not line.lstrip().startswith("- {")
        and "stock-Jinja" not in line and BARE.search(line.split("#", 1)[0])]
    assert not bare, f"{len(bare)} install_* reads without | bool:\n" + "\n".join(bare[:40])
