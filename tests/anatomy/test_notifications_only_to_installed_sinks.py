"""Notification dispatch targets only installed sinks; none installed is not a failure.

MEASURED 2026-10-15 on a client host (profiles/core.yml, no ntfy, no mail):
wing:dispatch-notifications failed every minute with "ntfy unreachable at
127.0.0.1:2586". post.yml rendered NTFY_URL="" — the documented off switch — and
the worker's `getenv() ?: default` turned "" back into the default port.
Here post.yml's env is RENDERED for core and the real worker is RUN with it.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "tools"), str(REPO / "files/anatomy")]
import nos_identity as ni  # noqa: E402
from module_utils import load_plugins as lp  # noqa: E402

POST = REPO / "roles/pazny.wing/tasks/post.yml"
WORKER = REPO / "files/anatomy/wing/bin/dispatch-notifications.php"


def _sinks(profile: str, **over) -> dict:
    flags = {**ni.install_flags(ni.profile_layers(REPO / "profiles" / profile)), **over}
    task = next(t for t in yaml.safe_load(POST.read_text(encoding="utf-8"))
                if "Discover Pulse job catalog" in t.get("name", ""))
    env = lp._jinja_env()
    env.undefined = jinja2.ChainableUndefined
    ctx = dict(flags, ntfy_port=2586, default_admin_email="op@example.test")
    return {k: env.from_string(str(task["environment"][k])).render(ctx)
            for k in ("NOS_NTFY_URL", "NOS_MAIL_HOST", "NOS_MAIL_RECIPIENT")}


def test_core_renders_no_sink() -> None:
    s = _sinks("core.yml")
    assert s["NOS_NTFY_URL"] == "" and s["NOS_MAIL_HOST"] == "", s


def test_an_installed_sink_is_targeted() -> None:
    assert _sinks("core.yml", install_ntfy=True)["NOS_NTFY_URL"] == "http://127.0.0.1:2586"
    assert _sinks("core.yml", install_mailpit=True)["NOS_MAIL_HOST"] == "127.0.0.1"


@pytest.mark.skipif(not shutil.which("php"), reason="php not on PATH")
def test_no_sink_is_none_configured_not_a_failure(tmp_path: Path) -> None:
    db = tmp_path / "wing.db"
    sqlite3.connect(db).close()
    s = _sinks("core.yml")
    r = subprocess.run([shutil.which("php"), str(WORKER)], capture_output=True, text=True, timeout=30,
                       env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin", "WING_DB_PATH": str(db),
                            "NTFY_URL": s["NOS_NTFY_URL"], "MAIL_HOST": s["NOS_MAIL_HOST"],
                            "MAIL_RECIPIENT": s["NOS_MAIL_RECIPIENT"]})
    assert r.returncode == 0, f"no sink installed → exit {r.returncode}: {r.stdout}{r.stderr}"
    assert "unreachable" not in r.stdout
    assert "none-configured" in r.stdout, r.stdout
