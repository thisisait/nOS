"""A failed health-wait prints the non-ready containers' own logs.

CI 37265044993: `iiab: 4/5 ready (waiting: keap-1[restarting])` for ten
minutes, then a fail that said nothing about why. The why (libsql CANTOPEN)
was in `docker logs keap-1`, which nobody running CI could see.

Pinned: (1) both fail paths of the health-wait — the tick abort and the budget
timeout — are directly preceded by an include of dump-unready-logs.yml under the
same condition; (2) `stack-health-probe.py --logs` prints the tail of exactly
the non-ready containers (fake docker on PATH, no daemon).
"""
from __future__ import annotations

import os
import pathlib
import stat
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
STACKS = REPO / "tasks" / "stacks"
PROBE = REPO / "files" / "anatomy" / "scripts" / "stack-health-probe.py"


def _preceding_dump(path: pathlib.Path, fail_name: str) -> None:
    tasks = yaml.safe_load(path.read_text(encoding="utf-8"))
    names = [str(t.get("name", "")) for t in tasks]
    i = next(i for i, n in enumerate(names) if fail_name in n)
    prev = tasks[i - 1]
    assert prev.get("ansible.builtin.include_tasks") == "dump-unready-logs.yml", (
        f"{path.name}: '{fail_name}' must be preceded by the non-ready log dump"
    )
    assert prev.get("when") == tasks[i].get("when"), "dump must run exactly when the fail does"


def test_tick_abort_dumps_logs_first() -> None:
    _preceding_dump(STACKS / "health-tick.yml", "Abort health-wait on FAILED/UNKNOWN")


def test_timeout_fail_dumps_logs_first() -> None:
    _preceding_dump(STACKS / "wait-stacks-healthy.yml", "Health-wait result")


def test_dump_file_calls_the_probe_logs_mode() -> None:
    body = (STACKS / "dump-unready-logs.yml").read_text(encoding="utf-8")
    assert "stack-health-probe.py" in body and "'--logs'" in body


def test_probe_logs_mode_tails_only_unready(tmp_path: pathlib.Path) -> None:
    fake = tmp_path / "docker"
    fake.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = ps ]; then\n'
        "  echo 'iiab-face-1|Up 2 minutes (healthy)'\n"
        "  echo 'iiab-keap-1|Restarting (1) 3 seconds ago'\n"
        'elif [ "$1" = logs ]; then echo "LOG-OF-$4" >&2; fi\n'
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    out = subprocess.run(
        [sys.executable, str(PROBE), "--logs", "iiab"],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "NOS_DOCKER_BIN": str(fake)},
    )
    assert out.returncode == 0
    assert "LOG-OF-iiab-keap-1" in out.stdout and "Restarting" in out.stdout
    assert "iiab-face-1" not in out.stdout


def test_probe_logs_mode_scrubs_secrets(tmp_path: pathlib.Path) -> None:
    """The dump lands in ansible output, the run log and CI; a container that
    echoes its env must not leak through it (pulse/redact.py shapes)."""
    fake = tmp_path / "docker"
    fake.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = ps ]; then echo "iiab-keap-1|Restarting (1) 3 seconds ago"\n'
        'elif [ "$1" = logs ]; then echo "DB_PASSWORD=hunter2hunter2 boot failed"\n'
        '  echo "mariadb-upgrade --password=s3cretPassVal"\n'
        '  echo "curl: Authorization: Bearer abcdefgh12345678xyz"\n'
        '  echo "retrying with Bearer tok9876543210abcdef"; fi\n'
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    out = subprocess.run(
        [sys.executable, str(PROBE), "--logs", "iiab"],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "NOS_DOCKER_BIN": str(fake)},
    )
    # every shape pulse/redact.py declares, not only the env one (PR #36 review)
    for secret in ("hunter2hunter2", "s3cretPassVal", "abcdefgh12345678xyz", "tok9876543210abcdef"):
        assert secret not in out.stdout, secret
    assert "DB_PASSWORD=<REDACTED> boot failed" in out.stdout
