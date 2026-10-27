"""A task that writes into Nextcloud's config/ on Linux runs with become.

MEASURED 2026-10-27, all-on lane (ubuntu-24.04): "Destination /home/runner/projects/nextcloud/config
not writable". The role hands config/ to www-data (uid 33) on Linux so the installer can write it,
then rendered the DB-TLS overlay into it as the runner user. macOS needs no become (file sharing).
"""
from __future__ import annotations

from pathlib import Path

import yaml

TASKS = Path(__file__).resolve().parents[2] / "roles/pazny.nextcloud/tasks/main.yml"
BECOME = "{{ ansible_os_family != 'Darwin' }}"


def test_every_write_into_config_is_become():
    writers = []
    for t in yaml.safe_load(TASKS.read_text()):
        for mod in ("ansible.builtin.template", "ansible.builtin.copy", "ansible.builtin.file",
                    "template", "copy", "file"):
            args = t.get(mod)
            if isinstance(args, dict) and "/config" in str(args.get("dest") or args.get("path") or ""):
                writers.append(t)
    assert len(writers) >= 2, "the config dir task and its overlay moved"
    missing = [t["name"] for t in writers if t.get("become") != BECOME]
    assert not missing, f"writes into config/ without become on Linux: {missing}"
