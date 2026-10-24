"""Paperclip's agents write files to a workspace that outlives the container.

WHY (2026-10-23, the operator's first Paperclip company): $81 of runs produced
13 Markdown documents in Paperclip's database and no website: the projects had
no workspace, so the agents' working files sat in /tmp inside the container
(1217 entries, lost on every restart) and nothing they built could be a file.
So every Paperclip gets a workspace root on the estate's storage (tenant-shared
content, class 2 of ssot/doctrine/filesystem.md, in the nightly backup), and the
operator may hand it named host folders (a client's repo) explicitly, one by one.
A host folder is never the estate's own state: ~/.nos (secrets, the estate
checkout), the data root itself, or the whole home are refused.
"""
from __future__ import annotations

import re
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
TPL = REPO / "roles/pazny.paperclip/templates/compose.yml.j2"
TASKS = REPO / "roles/pazny.paperclip/tasks/main.yml"
HOME = "/Users/op"


def _svc(**extra) -> dict:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["urlencode"] = str
    ctx = dict(paperclip_domain="paperclip.example.eu", paperclip_version="v", paperclip_port=3006,
               paperclip_data_dir="/data/paperclip", paperclip_workspaces_dir="/data/tenants/t/shared/paperclip/workspaces",
               paperclip_host_workspaces=[], services_lan_access=False, paperclip_mem_limit="3g",
               paperclip_db_user="u", paperclip_db_password="p", paperclip_db_name="d", postgresql_ssl_enabled=False,
               paperclip_openclaw_url="x", paperclip_auth_secret="s", service_extra_hosts=[], docker_mem_limit_standard="1g",
               docker_cpus_standard="2", stacks_dir="/stacks", stacks_shared_network="shared")
    ctx.update(extra)
    text = env.from_string(TPL.read_text()).render(**ctx)
    return next(iter(yaml.safe_load(text)["services"].values()))


def test_every_paperclip_has_a_workspace_root_on_the_estate_storage():
    vols = _svc()["volumes"]
    assert "/data/tenants/t/shared/paperclip/workspaces:/workspaces" in vols, vols
    tasks = yaml.safe_load(TASKS.read_text())
    made = [t for t in tasks if "paperclip_workspaces_dir" in str(t.get("ansible.builtin.file", {}))]
    assert made, "the role must create the workspace root"


def test_a_declared_host_folder_is_mounted_under_its_name():
    vols = _svc(paperclip_host_workspaces=[{"name": "hnedweb", "path": f"{HOME}/projects/hnedweb"},
                                           {"name": "ref", "path": f"{HOME}/projects/ref", "mode": "ro"}])["volumes"]
    assert f"{HOME}/projects/hnedweb:/workspaces/hnedweb:rw" in vols, vols
    assert f"{HOME}/projects/ref:/workspaces/ref:ro" in vols, vols


@pytest.mark.parametrize("path", [f"{HOME}/.nos", f"{HOME}/.nos/estate", "/data", HOME, f"{HOME}/"])
def test_the_estates_own_state_is_never_a_workspace(path):
    guard = [t for t in yaml.safe_load(TASKS.read_text()) if "ansible.builtin.assert" in t
             and "paperclip_host_workspaces" in str(t)]
    assert guard, "the role must refuse a host folder that is the estate's own state"
    that = guard[0]["ansible.builtin.assert"]["that"]
    env = jinja2.Environment()
    env.filters["realpath"] = lambda v: str(Path(v)).rstrip("/") or "/"
    env.tests["match"] = lambda v, pat: re.match(pat, str(v)) is not None  # ansible's test
    ok = all(env.from_string("{{ (" + c + ") | string }}").render(
        item={"name": "w", "path": path}, nos_data_root="/data",
        ansible_facts={"env": {"HOME": HOME}}) == "True" for c in that)
    assert not ok, f"{path} must be refused as a workspace"
    fine = all(env.from_string("{{ (" + c + ") | string }}").render(
        item={"name": "w", "path": f"{HOME}/projects/hnedweb"}, nos_data_root="/data",
        ansible_facts={"env": {"HOME": HOME}}) == "True" for c in that)
    assert fine, "a client's project folder is allowed"
