"""A template renders the host it runs on, never the maintainer's.

alloy-syslog tailed `/Users/<maintainer>/...` literally: on any other account
every daemon log was a silent empty glob. Hermes' memory seed named the
maintainer's address to every fork's agent. A .j2 derives home and identity
from facts/config; a literal home or the maintainer's address is red.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
OPERATOR = re.compile(r"/Users/[a-z][\w.-]*|pazny\.develop@|@pazny\.eu")


def test_no_template_names_the_operator() -> None:
    files = subprocess.run(["git", "ls-files", "*.j2"], cwd=REPO, capture_output=True,
                           text=True, check=True).stdout.split()
    hits = [f"{f}:{n}" for f in files
            for n, line in enumerate((REPO / f).read_text(encoding="utf-8").splitlines(), 1)
            if OPERATOR.search(line)]
    assert not hits, "template names a literal home or the maintainer:\n" + "\n".join(hits)
