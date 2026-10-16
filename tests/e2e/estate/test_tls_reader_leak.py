"""The redis AUTH secret never leaves tools/tls-uptake.py — checked live.

The offline twin (tests/anatomy/test_the_tls_reader_only_reads.py) proves the
same against a fake docker; this one reads the real container's argv, so it
lives on the e2e lane where the Docker VM's speed is the run's business.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOL = REPO / "tools/tls-uptake.py"
# ponytail: one generous ceiling; 2026-10-11 a starved VM took 190 s.
TOOL_TIMEOUT = 600


@pytest.mark.skipif(shutil.which("docker") is None,
                    reason="docker absent — the leak check needs the live container")
def test_the_redis_secret_never_appears_in_the_output():
    """The reader parses an argv that holds the estate's shared redis secret.
    This is the only check that can prove it did not carry it out."""
    probe = subprocess.run(
        ["docker", "inspect", "infra-redis-1", "--format", "{{json .Config.Cmd}}"],
        capture_output=True, text=True, timeout=60)
    if probe.returncode != 0:
        pytest.skip("infra-redis-1 not running — nothing to leak")
    argv = json.loads(probe.stdout or "[]")
    # `--requirepass` and its value are SEPARATE argv entries. The first cut of
    # this check split the flag token and found an empty tail, so it skipped
    # itself with the message "remediation (1) has landed" — a check reporting
    # the fix it was written to wait for. Exactly the shape this suite exists
    # to refuse, and it took two minutes to make.
    secrets = []
    for i, tok in enumerate(argv):
        if not isinstance(tok, str):
            continue
        if tok.strip() == "--requirepass" and i + 1 < len(argv):
            secrets.append(str(argv[i + 1]).strip().strip('"'))
        elif tok.startswith("--requirepass") and len(tok) > len("--requirepass "):
            secrets.append(tok.split("requirepass", 1)[1].strip().strip('"'))
    secrets = [s for s in secrets if len(s) >= 6]
    if not secrets:
        pytest.skip("no secret on the redis command line — remediation (1) has landed")

    for flags in ([], ["--json"]):
        p = subprocess.run([sys.executable, str(TOOL), *flags],
                           capture_output=True, text=True, timeout=TOOL_TIMEOUT, cwd=REPO)
        blob = p.stdout + p.stderr
        for secret in secrets:
            assert secret not in blob, (
                f"tools/tls-uptake.py {' '.join(flags)} printed the redis AUTH "
                "secret it inspected — the reader became a second copy of the "
                "exposure it reports")
