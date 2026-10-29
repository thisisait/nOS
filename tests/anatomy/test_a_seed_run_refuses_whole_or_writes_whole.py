"""A seed run checks every row against the live table before its first write, and --only files one row.

Measured 2026-10-28: `nos dtt seed` wrote 4 rows, then stopped on a row whose status is "" (KEAP's
400 "missing required column: status") — half a batch written, and no way to file one new row
without the 789 stale inserts riding along. Executed: tools/roadmap-seed.py against a fake KEAP
(schema + rows + the agent door), the joint between the seed files and the table definition.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCHEMA = [
    {"key": "slug", "kind": "text", "required": True}, {"key": "title", "kind": "text", "required": True},
    {"key": "parent", "kind": "text"}, {"key": "track", "kind": "text"}, {"key": "body", "kind": "text"},
    {"key": "status", "kind": "select", "required": True, "options": ["next", "queued", "shipped"]},
    {"key": "refs", "kind": "text"}, {"key": "release", "kind": "text"}, {"key": "task_type", "kind": "text"},
    {"key": "when", "kind": "text"}, {"key": "target", "kind": "date"}, {"key": "occurred_at", "kind": "date"},
]


def _keap(posts):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if "/rows" in self.path:
                self._send(200, {"data": {"rows": [{"id": "old", "values": {"slug": "old", "title": "Old"}}]}})
            else:
                self._send(200, {"data": {"schema": {"columns": SCHEMA}}})

        def do_POST(self):
            posts.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            self._send(200, {"success": True})

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _row(d: Path, slug: str, status: str):
    (d / f"{slug}.md").write_text(
        f'---\nslug: {slug}\ntitle: "{slug} title"\nparent: ""\ntrack: platform\ntask_type: design\n'
        f'status: "{status}"\nwhen: ""\nrefs: ""\nrelease: ""\n---\n\nbody of {slug}\n')


def _seed(tmp_path, *args):
    posts = []
    srv = _keap(posts)
    env = dict(os.environ, KEAP_API_URL=f"http://127.0.0.1:{srv.server_port}", KEAP_AGENT_TOKEN_RW="FAKE_rw",
               KEAP_PROXY_SHARED_SECRET="FAKE_proxy", KEAP_IDENTITY_URL="", NOS_ROADMAP_TABLE_ID="t",
               NOS_SEED_DIR=str(tmp_path / "seed"), PYTHONPATH=str(REPO / "tools"))
    r = subprocess.run([sys.executable, str(REPO / "tools/roadmap-seed.py"), *args],
                       capture_output=True, text=True, env=env, timeout=60, cwd=tmp_path)
    srv.shutdown()
    return r, posts


def _dir(tmp_path):
    d = tmp_path / "seed"
    d.mkdir()
    _row(d, "old", "next")
    _row(d, "good-new", "next")
    _row(d, "no-status", "")
    return d


def test_one_bad_row_refuses_the_run_before_any_write(tmp_path):
    _dir(tmp_path)
    r, posts = _seed(tmp_path)
    assert r.returncode != 0 and "no-status" in r.stdout + r.stderr, r.stdout + r.stderr
    assert posts == [], f"wrote before refusing: {[p.get('slug') for p in posts]}"


def test_only_files_the_named_row(tmp_path):
    _dir(tmp_path)
    r, posts = _seed(tmp_path, "--only", "good-new")
    assert r.returncode == 0, r.stdout + r.stderr
    assert [p["slug"] for p in posts] == ["good-new"]


def test_only_refuses_a_slug_no_file_has(tmp_path):
    _dir(tmp_path)
    r, posts = _seed(tmp_path, "--only=nope")
    assert r.returncode != 0 and "nope" in r.stdout + r.stderr and posts == []


def test_an_update_without_a_status_keeps_the_files_status(tmp_path):
    """Same day, the authoring side: two `dtt capture --update` runs without --status wrote
    status "" over `next`, which is exactly the row the seeder then refused."""
    d = tmp_path / "seed"
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    env = dict(os.environ, NOS_SEED_DIR=str(d))
    cap = [sys.executable, str(REPO / "tools/dtt-capture.py"), "--slug", "keep", "--title", "t",
           "--track", "platform", "--task-type", "design", "--body", "b"]
    assert subprocess.run(cap + ["--status", "next"], env=env, capture_output=True).returncode == 0
    r = subprocess.run(cap + ["--update", "--title", "t2"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert '\nstatus: next\n' in (d / "keep.md").read_text()
