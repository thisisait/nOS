"""test_hub_shows_estate_red reads the live estate only when the run declares it.

`@pytest.mark.live` lifts the offline boundary for the test that carries it, so
a plain `pytest tests/anatomy` opened ~/wing/app/data/wing.db and
~/.nos/secrets.yml and fetched Wing. Live is opt-in by the ENVIRONMENT
(NOS_LIVE=1), default off: undeclared, the file must skip without opening them.
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
TARGET = HERE / "test_hub_shows_estate_red.py"
# Records every open()/sqlite3.connect under the fake HOME, then runs the file.
PROBE = """
import sys, pytest
home, log = sys.argv[1], sys.argv[2]
def hook(event, args):
    if event in ("open", "sqlite3.connect") and args and home in str(args[0]):
        with open(log, "a") as f: f.write(str(args[0]) + "\\n")
sys.addaudithook(hook)
sys.exit(pytest.main(["-q", "-p", "no:cacheprovider", sys.argv[3]]))
"""


def test_undeclared_run_opens_nothing_of_the_estate(tmp_path) -> None:
    home = tmp_path / "home"
    (home / ".nos").mkdir(parents=True)
    (home / ".nos" / "secrets.yml").write_text("wing_edge_token: sentinel\n")
    db = home / "wing" / "app" / "data" / "wing.db"
    db.parent.mkdir(parents=True)
    sqlite3.connect(db).close()
    log = tmp_path / "opened.log"
    env = {k: v for k, v in os.environ.items() if k not in ("NOS_LIVE", "WING_DB_PATH")}
    env.update(HOME=str(home), NOS_WING_URL="http://127.0.0.1:9")  # never the real Wing
    r = subprocess.run([sys.executable, "-c", PROBE, str(home), str(log), str(TARGET)],
                       cwd=HERE, env=env, capture_output=True, text=True, timeout=120)
    opened = sorted({p for p in (log.read_text().splitlines() if log.exists() else [])
                     if "wing.db" in p or p.endswith("secrets.yml")})
    assert not opened, f"undeclared run opened the estate: {opened}\n{r.stdout[-800:]}"
    assert r.returncode == 0 and "3 skipped" in r.stdout, r.stdout[-800:]
