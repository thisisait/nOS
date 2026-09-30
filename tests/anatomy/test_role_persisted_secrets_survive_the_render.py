"""A key a role persists into ~/.nos/secrets.yml survives the next converge.

The central "[Secrets] Persist runtime secrets" task RE-RENDERS the whole
file from templates/secrets.yml.j2 every run. A key a role adds later with
lineinfile is kept only if the template names it. Found 2026-09-30: the
Woodpecker PAT and the MFA break-glass codes (seeded once, only copy) were
dropped on every converge after the one that wrote them.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _persisted_keys() -> dict[str, str]:
    keys: dict[str, str] = {}

    def walk(tasks, f):
        for t in tasks or []:
            if not isinstance(t, dict):
                continue
            for k in ("block", "rescue", "always"):
                walk(t.get(k), f)
            li = t.get("ansible.builtin.lineinfile") or t.get("lineinfile")
            if isinstance(li, dict) and "secrets.yml" in str(li.get("path", "")):
                m = re.match(r"\^([a-z0-9_]+):", str(li.get("regexp", "")))
                if m:
                    keys[m.group(1)] = f
                elif "{{ item.key }}" in str(li.get("regexp", "")):
                    for it in t.get("loop") or []:
                        if isinstance(it, dict) and "key" in it:
                            keys[it["key"]] = f

    for f in sorted(REPO.glob("roles/*/tasks/*.yml")) + sorted(REPO.glob("tasks/**/*.yml")):
        try:
            walk(yaml.safe_load(f.read_text(encoding="utf-8")), str(f.relative_to(REPO)))
        except yaml.YAMLError:
            continue
    return keys


def test_the_sweep_finds_the_known_writers():
    keys = _persisted_keys()
    assert {"gitea_api_token", "woodpecker_api_token", "authentik_break_glass_codes"} <= set(keys), keys


def test_every_role_persisted_key_is_in_the_template():
    tpl = (REPO / "templates/secrets.yml.j2").read_text(encoding="utf-8")
    missing = {k: f for k, f in _persisted_keys().items() if not re.search(rf"^{k}:", tpl, re.M)}
    assert not missing, f"re-rendered away on the next converge: {missing}"
