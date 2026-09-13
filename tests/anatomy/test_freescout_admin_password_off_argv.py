"""FreeScout admin password must not sit on docker exec / php artisan argv.

Pass the secret via stdin (or an env file). A ``command:`` / ``cmd:`` / ``shell:``
string that still interpolates ``freescout_admin_password`` is a leak: ``ps``
sees argv even when ``no_log: true`` hides ansible.log.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
PW = re.compile(r"\{\{[^}]*freescout_admin_password")
CMD_KEYS = {
    "cmd",
    "command",
    "shell",
    "ansible.builtin.shell",
    "ansible.builtin.command",
}
FILES = (
    REPO / "roles/pazny.freescout/tasks/post.yml",
    REPO / "files/anatomy/plugins/freescout-base/hooks/post_compose.yml",
)


def _command_strings(node):
    """Strings that become process argv. Never ``stdin``."""
    if isinstance(node, list):
        for item in node:
            yield from _command_strings(item)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key == "stdin":
            continue
        if key in CMD_KEYS:
            if isinstance(value, str) and value.strip():
                yield value
            elif isinstance(value, dict):
                cmd = value.get("cmd") or value.get("_raw_params")
                if isinstance(cmd, str):
                    yield cmd
            continue
        yield from _command_strings(value)


def test_freescout_admin_password_not_in_command_strings():
    hits = []
    for path in FILES:
        assert path.is_file(), f"missing {path.relative_to(REPO)}"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for blob in _command_strings(doc):
            if PW.search(blob):
                hits.append(str(path.relative_to(REPO)))
                break
    assert not hits, (
        "freescout_admin_password jinja still sits in a command string; "
        "pass via stdin or an env file:\n  " + "\n  ".join(hits)
    )

