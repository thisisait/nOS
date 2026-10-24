"""A converge releases the environment leases a Paperclip restart orphaned.

2026-10-24: 9 leases stood `active` on runs the restart had reaped to
`interrupted`, so every retry of those issues refused (upstream
paperclipai/paperclip#14672). The role releases them after the server is up,
and ONLY those: a lease whose run is still going, or already released, is not
touched.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
POST = REPO / "roles" / "pazny.paperclip" / "tasks" / "post.yml"


def _tasks():
    return yaml.safe_load(POST.read_text(encoding="utf-8"))


def _release():
    return next((t for t in _tasks() if "orphaned" in t.get("name", "")), None)


def test_the_role_releases_orphaned_leases():
    t = _release()
    assert t, "no task releases the leases a restart orphaned"
    sql = " ".join(t["ansible.builtin.shell"].split())
    assert "UPDATE environment_leases" in sql and "released_at = now()" in sql
    assert "l.released_at IS NULL" in sql, "would re-release leases that are already released"
    assert "r.status = 'interrupted'" in sql, "must release only leases whose run is over"
    assert "ON_ERROR_STOP=1" in sql, "a failed UPDATE would exit 0 and read as done"


def test_it_runs_after_the_server_is_up():
    names = [t.get("name", "") for t in _tasks()]
    up = names.index("[pazny.paperclip Post] Verify Paperclip HTTP (with correct Host header)")
    assert names.index(_release()["name"]) > up, "startup recovery marks runs interrupted; release after it"
