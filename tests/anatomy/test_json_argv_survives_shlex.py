"""Anatomy gate: a JSON argument must never be passed through a free-form command.

`ansible.builtin.command` avoids the SHELL, which is why it is reached for when a
value contains commas or braces. It does NOT avoid **shlex** — Ansible splits the
free-form string with `shlex.split`, and shlex strips quote characters. So

    php occ config:app:set onlyoffice defFormats --value={"csv":true,"doc":true}

arrives at the program as

    --value={csv:true,doc:true}

a JavaScript object literal, not JSON.

Measured live 2026-07-28. The ONLYOFFICE Nextcloud connector stores that string,
and `AppConfig::getDefaultFormats()` is declared `: array` while its body is
`json_decode($value, true)`. json_decode returns null for unquoted keys, PHP
raises `TypeError: Return value must be of type array, null returned`
(AppConfig.php:615), and because the call happens in `InitialStateService` during
template layout, **every page that renders the Files initial state returns 500** —
including `/apps/files/`. The stored value was byte-identical to shlex's output.

The task that wrote it had already reasoned about quoting once: its comment
explained that `shell:` would brace-expand the JSON, so it used `command:`. That
closed one hazard and opened this one. `argv:` closes both, because it bypasses
shell and shlex alike.

It also stayed invisible for as long as it did because the task carried
`no_log: true` (inherited by copy-paste from a sibling that genuinely holds a
secret) on top of `changed_when: false` and `failed_when: false` — three
independent silencers on a task that was writing corrupt data.
"""

from __future__ import annotations

import pathlib
import re
import shlex

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SEARCH = [REPO / "roles", REPO / "tasks"]

# A free-form command carrying a brace-and-quote payload. We look for the shape
# that shlex mangles: a double-quoted JSON key inside an unquoted argument.
JSON_ARG = re.compile(r'--?[\w-]+=\{\s*"')


def _task_files() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for root in SEARCH:
        out.extend(p for p in root.rglob("*.yml") if p.is_file())
    return sorted(out)


def _walk(node, path: str):
    """Yield (path, task-dict) for every mapping that looks like a task."""
    if isinstance(node, dict):
        if any(k in node for k in ("ansible.builtin.command", "command", "ansible.builtin.shell", "shell")):
            yield path, node
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def test_shlex_really_does_strip_the_quotes() -> None:
    """Pin the mechanism, so the gate cannot outlive its reason."""
    mangled = shlex.split('occ set --value={"csv":true,"doc":true}')
    assert mangled[-1] == "--value={csv:true,doc:true}", (
        "shlex no longer strips quotes from a free-form command string. If Ansible's "
        f"splitting changed, re-read this gate. Got: {mangled[-1]!r}"
    )


def test_no_free_form_command_carries_a_json_argument() -> None:
    offenders: list[str] = []
    for f in _task_files():
        try:
            doc = yaml.safe_load(f.read_text())
        except yaml.YAMLError:
            continue
        for where, task in _walk(doc, f.name):
            for key in ("ansible.builtin.command", "command", "ansible.builtin.shell", "shell"):
                val = task.get(key)
                # A dict form (argv:/cmd:) is not free-form; only a bare string is.
                if not isinstance(val, str):
                    continue
                if JSON_ARG.search(val):
                    name = task.get("name", where)
                    offenders.append(f"{f.relative_to(REPO)} :: {name}")
    assert not offenders, (
        "a task passes a JSON argument through a free-form command/shell string. Ansible "
        "splits these with shlex, which STRIPS the double quotes, so the program receives "
        "{key:true} instead of {\"key\":true} — valid JavaScript, invalid JSON. Use the "
        "`argv:` list form, which bypasses both the shell and shlex. Offenders:\n  "
        + "\n  ".join(offenders)
    )


def test_the_onlyoffice_formats_task_uses_argv() -> None:
    """The specific task this gate was written for, pinned by name."""
    doc = yaml.safe_load((REPO / "roles" / "pazny.nextcloud" / "tasks" / "post.yml").read_text())
    hits = [t for _, t in _walk(doc, "post") if "default editor for office formats" in str(t.get("name", ""))]
    assert hits, "the OnlyOffice default-formats task is gone — was it renamed, or lost?"
    cmd = hits[0].get("ansible.builtin.command")
    assert isinstance(cmd, dict) and "argv" in cmd, (
        "the OnlyOffice format-registration task is no longer using argv:. Its whole payload is "
        "JSON, and a free-form string form silently corrupts it into a 500 on /apps/files/."
    )


def test_that_task_does_not_hide_its_output() -> None:
    """no_log on a task with no secret is how corrupt data stays invisible."""
    doc = yaml.safe_load((REPO / "roles" / "pazny.nextcloud" / "tasks" / "post.yml").read_text())
    hits = [t for _, t in _walk(doc, "post") if "default editor for office formats" in str(t.get("name", ""))]
    assert hits and hits[0].get("no_log") is not True, (
        "the OnlyOffice format-registration task carries no_log: true again. It holds no secret "
        "(the jwt_secret is in the sibling task above), and combined with changed_when/failed_when "
        "false it could not report a bad write by construction."
    )
