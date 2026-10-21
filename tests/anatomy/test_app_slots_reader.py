"""tools/app-slots.py answers "is this app name / subdomain / host port free here".

WHY. propose_app (Iris) and the parser's --estate check ask it before a draft
exists; a source it could not read must make the answer null, never "free" —
a free that was never checked is how a second app lands on a taken port.

HOW. A throwaway repo (the tool + nos_identity copied in, so REPO resolves
there) and a throwaway HOME; one row of each kind taken; the contract the Iris
tool parses is pinned key by key.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def rig(tmp_path):
    repo, home = tmp_path / "repo", tmp_path / "home"
    (repo / "tools").mkdir(parents=True)
    for f in ("app-slots.py", "nos_identity.py"):
        shutil.copy(REPO / "tools" / f, repo / "tools" / f)
    (repo / "state").mkdir()
    (repo / "state/manifest.yml").write_text(
        "services:\n  - id: next_cloud\n    domain_var: nextcloud_domain\n    port_var: nextcloud_port\n")
    (repo / "config.d").mkdir()
    (repo / "config.d/10-test.yml").write_text(
        "tenant_domain: dev.local\nnextcloud_domain: \"cloud.{{ tenant_domain }}\"\nnextcloud_port: 8100\n")
    (repo / "roles/pazny.gitea").mkdir(parents=True)
    (repo / "apps").mkdir()
    (repo / "apps/notes.yml.draft").write_text(
        "meta: {name: notes, ports: [8101]}\ncompose: {services: {notes: {ports: ['127.0.0.1:8102:80']}}}\n")
    conf = home / "stacks/infra/traefik/conf.d"
    conf.mkdir(parents=True)
    (conf / "services.yml").write_text("http:\n  routers:\n    w:\n      rule: Host(`wiki.dev.local`)\n")

    def run(*args):
        env = {**os.environ, "HOME": str(home)}
        p = subprocess.run([sys.executable, str(repo / "tools/app-slots.py"), "--json", *args],
                           capture_output=True, text=True, env=env, timeout=60)
        assert p.returncode == 0, p.stderr
        return json.loads(p.stdout)
    run.repo, run.home = repo, home
    return run


def test_the_contract_keys(rig):
    out = rig("--name", "x", "--subdomain", "x", "--port", "9", "--free-port")
    assert set(out) == {"names_taken", "subdomains_taken", "ports_taken", "checks", "free_port", "sources", "unknown"}
    assert set(out["checks"]) == {"name", "subdomain", "port"}
    assert set(out["sources"]) == {"manifest", "apps", "traefik"}
    assert all(set(c) == {"value", "free", "why"} for c in out["checks"].values())
    assert set(rig()["checks"]) == set()


def test_taken_from_every_source(rig):
    out = rig()
    assert {"next-cloud", "gitea", "notes"} <= set(out["names_taken"])
    assert {"cloud", "notes", "wiki"} <= set(out["subdomains_taken"])
    assert {8100, 8101, 8102} <= set(out["ports_taken"])
    assert out["sources"] == {"manifest": "ok", "apps": "ok", "traefik": "ok"} and out["unknown"] == []
    for args, kind in ((("--name", "gitea"), "name"), (("--subdomain", "wiki"), "subdomain"),
                       (("--port", "8102"), "port"), (("--name", "next-cloud"), "name")):
        c = rig(*args)["checks"][kind]
        assert c["free"] is False and c["why"].startswith("taken"), c


def test_free_and_free_port(rig):
    out = rig("--name", "ledger", "--subdomain", "ledger", "--port", "8200", "--free-port")
    assert [c["free"] for c in out["checks"].values()] == [True, True, True]
    assert out["free_port"] == 8103  # 8100-8102 taken
    assert rig("--free-port", "--from", "8100", "--to", "8102")["free_port"] is None


def test_an_unreadable_source_is_unknown_never_free(rig):
    shutil.rmtree(rig.home / "stacks")
    out = rig("--subdomain", "ledger", "--name", "ledger", "--subdomain", "ledger")
    assert out["sources"]["traefik"].startswith("UNKNOWN")
    assert out["checks"]["subdomain"]["free"] is None and out["checks"]["name"]["free"] is True
    assert any(u.startswith("traefik") for u in out["unknown"])
    (rig.repo / "state/manifest.yml").write_text("services: [")
    out = rig("--name", "ledger", "--port", "8200", "--free-port")
    assert out["sources"]["manifest"].startswith("UNKNOWN")
    assert out["checks"]["name"]["free"] is None and out["checks"]["port"]["free"] is None
    assert out["free_port"] is None
    assert rig("--name", "notes")["checks"]["name"]["free"] is False  # a read source still knows


def test_live_adds_the_listening_source(rig):
    out = rig("--live", "--port", "8200")
    assert "listening" in out["sources"]
    if out["sources"]["listening"] != "ok":
        assert out["checks"]["port"]["free"] is None
