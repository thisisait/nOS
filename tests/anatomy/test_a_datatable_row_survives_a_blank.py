"""Anatomy gate — a DataTable row and its moved status survive a blank.

The blanks of 2026-10-09 and 10-17 wiped keap.db; the roadmap's table-owned
half (status, verified, occurred_at) was lost because the seed files carry only
the git half. The joint is tools/keap-tables.py ↔ KEAP's API: rehearsed here on
the PINNED KEAP image — export from one scratch instance, wipe (a second one,
reseeded with the git half only), import, read the row back.
Live-marked (docker + a loopback port): NOS_LIVE=1 python3 -m pytest -m live -k blank.
Touches only its own scratch containers; skips when the pinned image is absent.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "keap-tables.py"
SECRET, RW = "scratch-proxy", "scratch-rw"
UUID_T = "0b5e7e1a-2c3d-4e5f-8a9b-0c1d2e3f4a5b"


def _image():
    ver = re.search(r'^keap_version:\s*"([^"]+)"', (REPO / "default.config.yml").read_text(), re.M).group(1)
    if not shutil.which("docker"):
        return None
    out = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}", "nos/keap"],
                         capture_output=True, text=True).stdout.split()
    tags = sorted(t for t in out if t.startswith(f"nos/keap:{ver}-"))
    return tags[-1] if tags else None


pytestmark = pytest.mark.live
IMAGE = None


class Keap:
    def __init__(self):
        global IMAGE
        IMAGE = IMAGE or _image()
        if not IMAGE:
            pytest.skip("needs docker and the pinned nos/keap image")
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.url = f"http://127.0.0.1:{self.port}"
        self.cid = subprocess.run(
            ["docker", "run", "-d", "--rm", "-p", f"127.0.0.1:{self.port}:8080", "--tmpfs", "/data:mode=1777",
             "-e", "PORT=8080", "-e", "KEAP_DATA_DIR=/data", "-e", "KEAP_TRUSTED_PROXY=1",
             "-e", f"KEAP_PROXY_SHARED_SECRET={SECRET}", "-e", f"KEAP_AGENT_TOKEN_RW={RW}",
             "-e", "KEAP_AGENT_TOKEN_RO=scratch-ro", IMAGE],
            capture_output=True, text=True, check=True).stdout.strip()
        for _ in range(90):
            try:
                urllib.request.urlopen(f"{self.url}/api/health", timeout=2)
                return
            except (urllib.error.URLError, OSError):
                time.sleep(1)
        self.stop()
        raise RuntimeError("scratch KEAP never became healthy")

    def stop(self):
        subprocess.run(["docker", "rm", "-f", self.cid], capture_output=True)

    def call(self, method, path, body=None, user="akadmin", agent=False):
        hdr = ({"authorization": f"Bearer {RW}"} if agent else
               {"X-Authentik-Username": user, "X-Authentik-Email": f"{user}@x", "x-keap-proxy-secret": SECRET,
                "X-Authentik-Groups": "nos-providers,nos-admins"})
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={**hdr, "content-type": "application/json"}, method=method)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["data"]

    def tool(self, *args, bundles):
        env = {**os.environ, "KEAP_API_URL": self.url, "KEAP_PROXY_SHARED_SECRET": SECRET,
               "KEAP_AGENT_TOKEN_RW": RW, "KEAP_TABLES_BUNDLE_DIR": str(bundles), "KEAP_IDENTITY_URL": ""}
        return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env)


GIT_HALF = [{"key": "slug", "label": "Slug", "kind": "text", "role": "dimension"},
            {"key": "title", "label": "Title", "kind": "text", "role": "dimension"}]
STATUS = {"key": "status", "label": "Status", "kind": "select", "role": "dimension", "options": ["queued", "shipped"]}


def _row(keap, table, rid):
    return {r["id"]: r for r in keap.call("GET", f"/api/tables/{table}/rows?limit=500")["rows"]}.get(rid)


def test_a_row_and_its_status_come_back_after_a_blank(tmp_path):
    bundles = tmp_path / "keap-tables"
    old = Keap()
    try:
        old.call("POST", "/agent/v1/tables", {"slug": "roadmap", "title": "Roadmap", "visibility": "tier-managers",
                                              "columns": GIT_HALF + [STATUS]}, agent=True)
        old.call("POST", "/api/tables/roadmap/rows", {"id": "r1", "values": {"slug": "r1", "title": "T", "status": "queued"}})
        old.call("POST", "/api/tables/roadmap/rows", {"id": "r1", "values": {"status": "shipped"}})   # nos dtt update
        old.call("POST", "/api/tables", {"id": UUID_T, "title": "Mine", "visibility": "shared",
                                         "schema": {"columns": GIT_HALF}}, user="pazny")
        old.call("POST", f"/api/tables/{UUID_T}/rows", {"id": "m1", "values": {"slug": "m1", "title": "kept"}})
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5))
        dry = old.tool("export", bundles=bundles)
        assert dry.returncode == 0 and "roadmap" in dry.stdout and not bundles.exists(), dry.stdout + dry.stderr
        out = old.tool("export", "--confirm", "--since", since, bundles=bundles)
        assert out.returncode == 0 and "WROTE" in out.stdout, out.stdout + out.stderr
    finally:
        old.stop()

    new = Keap()   # the wipe: a fresh keap.db, reseeded with the git half only
    try:
        new.call("POST", "/agent/v1/tables", {"slug": "roadmap", "title": "Roadmap", "visibility": "tier-managers",
                                              "columns": GIT_HALF}, agent=True)
        new.call("POST", "/api/tables/roadmap/rows", {"id": "r1", "values": {"slug": "r1", "title": "T"}})

        stale = new.tool("import", "--confirm", "--since", "2099-01-01T00:00:00Z", bundles=bundles)
        assert stale.returncode == 3 and "REFUSING" in stale.stdout, stale.stdout + stale.stderr
        dry = new.tool("import", "--since", since, bundles=bundles)
        assert dry.returncode == 0 and "DRY RUN" in dry.stdout, dry.stdout + dry.stderr
        assert "status" not in _row(new, "roadmap", "r1")["values"]

        got = new.tool("import", "--confirm", "--since", since, bundles=bundles)
        assert got.returncode == 0, got.stdout + got.stderr
        assert _row(new, "roadmap", "r1")["values"] == {"slug": "r1", "title": "T", "status": "shipped"}
        mine = new.call("GET", f"/api/tables/{UUID_T}")
        assert mine["ownerId"] == "pazny" and _row(new, UUID_T, "m1")["values"]["title"] == "kept"

        again = new.tool("import", "--confirm", "--since", since, bundles=bundles)
        assert again.returncode == 0 and "WROTE 0 rows" in again.stdout, again.stdout + again.stderr
    finally:
        new.stop()
