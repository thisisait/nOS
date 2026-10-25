"""A task that carries a secret in its arguments or its facts is `no_log: true`.

MEASURED 2026-10-25 (row pulse-redact-gaps): the audit ledger `events` held a
Wing bearer token 98 times (`uri` with `Authorization: Bearer {{ wing_api_token }}`
in a loop, roles/pazny.wing/tasks/post.yml), backup_encryption_passphrase in 42
rows (a set_fact in main.yml) and Authentik session cookies in 3 (a uri probe in
tasks/iiab/stack_verify.yml). The telemetry callback scrubs by key name, which is
defence in depth; the control is that Ansible never hands the callback the value.
Read from the YAML, every task file: a uri/get_url with an auth/cookie/token
header or a password argument, and a set_fact with a secret-shaped key, must say
no_log: true. A templated `no_log:` expression counts (it is the author's decision).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
ROOTS = ["main.yml", "tasks", "roles", "playbooks"]
HTTP = {"uri", "ansible.builtin.uri", "get_url", "ansible.builtin.get_url"}
FACT = {"set_fact", "ansible.builtin.set_fact"}
SECRET_HEADER = re.compile(r"authorization|cookie|token|api[-_]?key|secret", re.I)
SECRET_ARG = {"url_password", "password", "client_secret"}
SECRET_KEY = re.compile(r"password|passphrase|token|secret|credential|_key$|^key$|app_key", re.I)
# A fact ABOUT a secret is not one: whether it exists, is usable, how many, their names.
ABOUT = re.compile(r"_(exists|usable|count|names)$")


class _Loader(yaml.SafeLoader):
    """`!vault` / `!unsafe` and friends: the value is not this gate's business."""


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _tasks(node):
    if isinstance(node, list):
        for t in node:
            yield from _tasks(t)
    elif isinstance(node, dict):
        if any(k in node for k in HTTP | FACT):
            yield node
        for k in ("block", "rescue", "always", "tasks", "pre_tasks", "post_tasks", "handlers"):
            yield from _tasks(node.get(k))


def _files():
    for root in ROOTS:
        p = REPO / root
        yield from ([p] if p.is_file() else sorted(p.rglob("*.yml")))


def _leaks(task) -> str | None:
    if task.get("no_log") not in (None, False, "false", "False"):
        return None
    for mod in HTTP & task.keys():
        args = task[mod] if isinstance(task[mod], dict) else {}
        hdr = [h for h in (args.get("headers") or {}) if SECRET_HEADER.search(str(h))]
        if hdr or SECRET_ARG & args.keys():
            return f"{mod} with {hdr or sorted(SECRET_ARG & args.keys())}"
    for mod in FACT & task.keys():
        args = task[mod] if isinstance(task[mod], dict) else {}
        keys = sorted(k for k in args if k != "cacheable" and SECRET_KEY.search(str(k)) and not ABOUT.search(str(k)))
        if keys:
            return f"set_fact of {keys[:4]}{' …' if len(keys) > 4 else ''}"
    return None


def test_secret_bearing_tasks_are_no_log():
    found = []
    for f in _files():
        if "/files/" in str(f) or "/templates/" in str(f) or "/molecule/" in str(f):
            continue
        try:
            doc = yaml.load(f.read_text(encoding="utf-8"), Loader=_Loader)
        except yaml.YAMLError:
            continue
        for t in _tasks(doc):
            why = _leaks(t)
            if why:
                found.append(f"{f.relative_to(REPO)}: {t.get('name', '?')} — {why}")
    assert not found, f"{len(found)} secret-bearing task(s) without no_log:\n  " + "\n  ".join(found)
