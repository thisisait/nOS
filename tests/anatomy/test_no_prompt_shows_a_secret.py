"""No interactive prompt prints a secret, and the password-prefix prompt does not echo.

Found 2026-10-17 during a blank: '[Prefix] Prompt for password prefix' showed the live prefix as
its default ('Enter = {{ global_password_prefix }}'), on screen and in the tee'd converge log;
the prefix roots the legacy derived passwords. A prompt names what Enter does, never the value.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SECRETISH = re.compile(r"password|prefix|secret|token|api_key|_key\b|credential", re.I)


def _secret_vars() -> set[str]:
    creds = yaml.safe_load((REPO / "default.credentials.yml").read_text(encoding="utf-8")) or {}
    return set(creds) | {"global_password_prefix"}


def _tasks(node):
    if isinstance(node, list):
        for x in node:
            yield from _tasks(x)
    elif isinstance(node, dict):
        if "pause" in node or "ansible.builtin.pause" in node:
            yield node
        for k in ("block", "rescue", "always", "tasks", "pre_tasks", "post_tasks", "handlers"):
            yield from _tasks(node.get(k))


def _prompts():
    files = [REPO / "main.yml", *REPO.glob("tasks/**/*.yml"), *REPO.glob("roles/*/tasks/**/*.yml")]
    for f in files:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        for play in doc if isinstance(doc, list) else []:
            for vp in (play or {}).get("vars_prompt") or [] if isinstance(play, dict) else []:
                yield f, vp.get("name"), str(vp.get("prompt", "")), vp
        for t in _tasks(doc):
            p = t.get("pause") or t.get("ansible.builtin.pause") or {}
            yield f, t.get("name"), str(p.get("prompt", "")) if isinstance(p, dict) else "", p


def test_no_prompt_interpolates_a_secret():
    secrets = _secret_vars()
    bad = []
    for f, name, prompt, _ in _prompts():
        for expr in re.findall(r"\{\{(.*?)\}\}", prompt):
            words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr))
            if words & secrets or any(SECRETISH.search(w) for w in words):
                bad.append(f"{f.relative_to(REPO)}: {name!r} shows {{{{{expr.strip()}}}}}")
    assert not bad, "a prompt prints a secret on screen and into every tee'd log:\n" + "\n".join(bad)


def test_the_prefix_prompt_does_not_echo_what_is_typed():
    hits = [(f, n, p) for f, n, _, p in _prompts() if n and "password prefix" in n.lower()]
    assert hits, "the password-prefix prompt is gone: re-point this gate"
    for f, n, p in hits:
        assert p.get("echo") is False, f"{f.relative_to(REPO)}: {n!r} echoes the new prefix as it is typed"
