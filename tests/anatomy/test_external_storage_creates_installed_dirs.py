"""Gate: external-storage.yml creates data dirs only for installed services.

2026-10-16: it pre-created every service's dir on the SSD, installed or not; the
backup then found gitea/vaultwarden/... dirs present on a core host that runs
none of them. Each loop item now names the flag its service runs under, and the
loop is evaluated here against the core profile's resolved flags.
"""
import re
import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

TASK = "[External SSD] Create data directories from override vars"


def _task():
    tasks = yaml.safe_load((REPO / "tasks/external-storage.yml").read_text(encoding="utf-8"))
    return next(t for t in tasks if t.get("name") == TASK)


def test_every_item_names_its_flag():
    bad = [i for i in _task()["loop"] if not isinstance(i, dict) or "enabled" not in i]
    assert not bad, f"loop items without an `enabled` flag: {bad}"


def test_core_creates_no_dir_of_a_service_it_does_not_run():
    flags = ni.install_flags(ni.profile_layers(REPO / "profiles/core.yml"))
    cfg = ni.default_config()
    env = jinja2.Environment()
    env.filters["bool"] = lambda v: str(v).lower() in ("1", "true", "yes")
    env.filters["default"] = lambda v, d=None: d if isinstance(v, jinja2.Undefined) else v
    task = _task()
    created = []
    for item in task["loop"]:
        on = env.from_string(str(item["enabled"])).render({**cfg, **flags})
        if on.strip().lower() in ("true", "1"):
            created.append(re.sub(r"[{} ]", "", item["path"]))
    assert "when" in task and "item.enabled" in str(task["when"]), task.get("when")
    off = [p for p in created if re.search(r"(gitea|gitlab|vaultwarden|n8n|mariadb|nextcloud|jellyfin)", p)]
    assert not off, f"core creates dirs of services it never installed: {off}"
    assert any("postgresql_data_dir" in p for p in created), created
