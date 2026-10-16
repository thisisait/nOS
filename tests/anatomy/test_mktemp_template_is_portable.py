"""`mktemp -t <name>` without X's works on macOS and dies on Linux.

BSD mktemp treats a bare `-t` argument as a prefix and appends its own random
part; GNU coreutils demands >= 3 X's and exits 1 ("too few X's in template").
backup.sh's tar member list used `-t nosbackup`: on Linux the `2>""` redirect
then failed, so EVERY dir-* source recorded FAILED (rc=1). Caught 2026-10-16 only
because the Linux CI runner executes run_dirs; a macOS-only run stays green.
CI-safe: source scan.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# The template is the first non-option word after `mktemp`'s options.
CALL = re.compile(r"\bmktemp((?:\s+-[A-Za-z]+)*)\s+-t\s+([^\s)\"';|]+)")


def test_every_mktemp_t_template_has_xs() -> None:
    files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True,
                           check=True).stdout.splitlines()
    bad = []
    for f in files:
        p = REPO / f
        if p.suffix not in {".sh", ".j2", ".yml", ".yaml", ".bash", ""} or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for m in CALL.finditer(line):
                if "XXX" not in m.group(2):
                    bad.append(f"{f}:{n}: {m.group(0)}")
    assert not bad, "GNU mktemp needs >= 3 X's in a -t template (BSD does not):\n" + "\n".join(bad)
