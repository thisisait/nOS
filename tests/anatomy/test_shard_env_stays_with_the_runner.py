"""NOS_PYTEST_SHARD belongs to the CI runner's own session, never to a pytest a test spawns.

CI dev 48862610 (2026-10-15): shard 3/4 ran test_absence_is_counted, whose inner pytest
inherited NOS_PYTEST_SHARD=3/4, deselected its one file and exited 5 ("no tests ran").
The hook reads the spec once and takes it out of the environment."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_a_test_never_sees_the_shard_spec(tmp_path):
    probe = tmp_path / "test_probe.py"
    probe.write_text("import os\n\ndef test_probe():\n    assert 'NOS_PYTEST_SHARD' not in os.environ\n")
    env = {**os.environ, "PYTHONPATH": str(REPO / "tests"), "NOS_PYTEST_SHARD": "1/1"}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "_shard", str(probe)],
                       cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
