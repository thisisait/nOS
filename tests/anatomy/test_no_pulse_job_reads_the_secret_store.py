"""No script a Pulse job runs opens secrets.yml / credentials.yml itself, and the medulla refuses one that does.

A job that reads the store itself carries no `secret:` env, so pulse-medulla-split saw gitea:trunk-sync
as secret-free (row jobs-that-read-secrets-yml), and a sealed store (secrets-at-rest) would have a
second reader. KNOWN_READERS is the debt still to move; it may only shrink.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "files/anatomy/scripts/pulse-medulla-split.py"
KNOWN_READERS = {
    "n8n:exec-watch", "loop:drive", "loop:review", "librarian:judge-lint-queue", "librarian:brief-taxonomy",
    "librarian:describe-taxonomy", "surveyor:surface-survey", "upgrade-architect:recipe-author",
    "conductor:self-test-001",
}


def _catalog() -> list[dict]:
    out = subprocess.run([sys.executable, str(REPO / "files/anatomy/scripts/discover-pulse-catalog.py")],
                         env={**os.environ, "NOS_PLAYBOOK_DIR": str(REPO)}, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _split(ids: str, catalog: list[dict]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CHECK)], input=json.dumps(catalog), capture_output=True, text=True,
                          env={**os.environ, "PULSE_MEDULLA_JOBS": ids}, timeout=60)


def test_only_the_known_jobs_read_the_store_and_the_list_only_shrinks():
    catalog = _catalog()
    ids = ",".join(f"{e['plugin_name'].removesuffix('-base')}:{e['job']['name']}" for e in catalog if "job" in e)
    refused = {line.split(":", 2)[0] + ":" + line.split(":", 2)[1]
               for line in _split(ids, catalog).stdout.splitlines() if "reads the secret store itself" in line}
    assert refused - KNOWN_READERS == set(), f"new job(s) read secrets.yml themselves: {sorted(refused - KNOWN_READERS)}"
    assert KNOWN_READERS - refused == set(), f"moved off the store, drop from KNOWN_READERS: {sorted(KNOWN_READERS - refused)}"


def test_the_split_refuses_a_script_that_reads_the_store_but_not_a_comment(tmp_path):
    reader, talker = tmp_path / "reader.sh", tmp_path / "talker.py"
    reader.write_text('#!/bin/sh\nT=$(grep token "$HOME/.nos/secrets.yml")\n')
    talker.write_text('"""Never reads ~/.nos/secrets.yml."""\n# nor credentials.yml\nprint("default.credentials.yml")\n')
    catalog = [{"plugin_name": "x-base", "job": {"name": "reader", "command": str(reader)}},
               {"plugin_name": "x-base", "job": {"name": "talker", "command": "python3", "args": [str(talker)]}}]
    out = _split("x:reader,x:talker", catalog)
    assert out.returncode == 1 and "x:reader: reader.sh reads the secret store itself" in out.stdout, out
    assert "x:talker" not in out.stdout, out.stdout
