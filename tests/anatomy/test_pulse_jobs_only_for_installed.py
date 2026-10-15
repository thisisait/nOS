"""Pulse schedules jobs only for what this host installed.

MEASURED 2026-10-15 on a client host converged with profiles/core.yml: Pulse held
jobs for gitea/gitlab trunk-sync, n8n exec-watch, geolibre, crm-hydrate,
alert-relay... — none installed — failing rc=126 or overdue on every tick. The
catalog is RUN here with core's resolved flags (nos_identity) and post.yml's
upsert/DELETE loops are RENDERED over it: what is registered, what is dropped.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "tools"), str(REPO / "files/anatomy")]
import nos_identity as ni  # noqa: E402
from module_utils import load_plugins as lp  # noqa: E402

CATALOG = REPO / "files/anatomy/scripts/discover-pulse-catalog.py"
POST = REPO / "roles/pazny.wing/tasks/post.yml"
PLUGINS = {p.parent.name: yaml.safe_load(p.read_text(encoding="utf-8")) or {}
           for p in (REPO / "files/anatomy/plugins").glob("*/plugin.yml")}
#: Owners core does not install, each seen scheduled on the client host.
NOT_ON_CORE = {"gitea-base", "gitlab-base", "n8n-base", "geolibre-base",
               "crm-hydrate-base", "alert-relay-base", "backup-base", "cortex-base"}


def _flags(profile: str = "core.yml") -> dict:
    return ni.install_flags(ni.profile_layers(REPO / "profiles" / profile))


def catalog(flags: dict) -> list[dict]:
    env = {**os.environ, "NOS_PLAYBOOK_DIR": str(REPO), "NOS_INSTALL_FLAGS": json.dumps(flags)}
    out = subprocess.run([sys.executable, str(CATALOG)], capture_output=True,
                         text=True, env=env, check=True).stdout
    return json.loads(out)


def _task(fragment: str) -> dict:
    tasks = yaml.safe_load(POST.read_text(encoding="utf-8"))
    return next(t for t in tasks if fragment in t.get("name", ""))


def _ids(task: dict, cat: list[dict]) -> set[str]:
    """Render the task's loop over `cat`, then its uri url/body per item → job ids."""
    env = lp._jinja_env()
    env.undefined = jinja2.ChainableUndefined
    items = env.from_string("{{ (" + task["loop"].strip()[2:-2] + ") | to_json }}").render(
        _pulse_catalog=cat)
    uri = task["ansible.builtin.uri"]
    out = set()
    for item in json.loads(items):
        if uri["method"] == "DELETE":
            out.add(env.from_string(uri["url"]).render(item=item, wing_port=9000).rsplit("/", 1)[-1])
        else:
            body = {k: env.from_string(str(v)).render(item=item) for k, v in uri["body"].items()
                    if k in ("plugin_name", "job_name")}
            out.add(f"{body['plugin_name']}:{body['job_name']}")
    return out


def registered(flags: dict) -> set[str]:
    return _ids(_task("Register discovered Pulse jobs"), catalog(flags))


def dropped(flags: dict) -> set[str]:
    return _ids(_task("Drop Pulse jobs of services not installed"), catalog(flags))


def _owner_on(plugin: str, flags: dict) -> bool:
    req = PLUGINS[plugin].get("requires") or {}
    flag = req.get("feature_flag")
    peers = req.get("plugin") or []
    return (not flag or flags.get(flag) is True) and all(
        _owner_on(p, flags) for p in ([peers] if isinstance(peers, str) else peers))


def test_core_schedules_no_job_of_a_service_it_did_not_install() -> None:
    flags = _flags()
    on = registered(flags)
    stray = sorted(j for j in on for p in NOT_ON_CORE if j.startswith(p.removesuffix("-base") + ":"))
    assert not stray, f"core host: Pulse would schedule {stray}; their services are not installed"
    for e in catalog(flags):
        if e["source"].startswith("plugins/") and e.get("installed", True):
            plugin = e["source"].split("/")[1]
            assert _owner_on(plugin, flags), f"core host: {plugin}:{e['job']['name']} scheduled, owner off"
    assert {"wing:dispatch-notifications", "keap:keap-embed-sync"} <= on


def test_a_service_switched_off_has_its_jobs_dropped() -> None:
    gone = dropped(_flags())
    assert {"gitea:trunk-sync", "n8n:exec-watch", "crm-hydrate:hydrate-parties"} <= gone
    assert not gone & registered(_flags()), "a job may not be both registered and dropped"


def test_a_service_switched_on_adds_its_jobs() -> None:
    # trunk-sync is also owned by install_loops (ruling 2026-10-15), off on core
    flags = dict(_flags(), install_gitea=True, install_n8n=True, install_loops=True)
    on = registered(flags)
    assert {"gitea:trunk-sync", "n8n:exec-watch"} <= on
    assert not {"gitea:trunk-sync", "n8n:exec-watch"} & dropped(flags)


def test_post_yml_hands_the_catalog_the_resolved_flags() -> None:
    env = _task("Discover Pulse job catalog")["environment"]
    assert "NOS_INSTALL_FLAGS" in env, "the catalog cannot filter without the host's install_* flags"
