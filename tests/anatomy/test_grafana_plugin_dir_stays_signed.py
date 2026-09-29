"""pazny.grafana must not write into the signed plugin's directory.

Grafana verifies a signed plugin against its MANIFEST.txt; any file the
manifest does not list makes the signature "modified" and the plugin is
skipped — silently for the health-wait, since Grafana stays healthy. The
2026-09-26 host-side provisioning stamped `.nos-version-<v>` INSIDE the dir
and every wing_sqlite / keap_sqlite dashboard went dark until 2026-09-29.
The installed version is read from plugin.json instead.
"""
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "roles/pazny.grafana/tasks/main.yml"
PLUGIN_DIR = "frser-sqlite-datasource/"


def _walk(tasks):
    for t in tasks:
        yield t
        yield from _walk(t.get("block", []))


def _writers():
    for t in _walk(yaml.safe_load(TASKS.read_text())):
        for mod in ("ansible.builtin.copy", "ansible.builtin.template", "ansible.builtin.file"):
            spec = t.get(mod)
            if isinstance(spec, dict) and spec.get("state") != "absent" and PLUGIN_DIR in str(spec.get("dest") or spec.get("path") or ""):
                yield t["name"]


def test_nothing_is_written_inside_the_signed_plugin_dir() -> None:
    assert list(_writers()) == []


def test_the_installed_version_is_read_from_plugin_json() -> None:
    text = TASKS.read_text()
    assert "plugin.json" in text and ".nos-version-{{" not in text
