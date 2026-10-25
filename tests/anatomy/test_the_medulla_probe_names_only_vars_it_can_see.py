"""The opt-in medulla probe (pazny.thalamus macos.yml) names only variables visible from that role.

MEASURED 2026-10-25: the probe called `{{ medulla_bin }}`, a default of pazny.medulla, from
pazny.thalamus; the live converge died with "'medulla_bin' is undefined" after 218 green tasks.
A role's defaults are not its includer's. Each variable the probe renders must come from the
committed global layers, the thalamus role's defaults, a register in the same file, or Ansible.
"""
from __future__ import annotations

import sys
from pathlib import Path

import jinja2
import jinja2.meta
import yaml

REPO = Path(__file__).resolve().parents[2]
ANSIBLE = {"ansible_facts", "playbook_dir", "item", "inventory_hostname", "hostvars",
           "medulla_pulse_probe"}  # the last: the operator's -e switch, read with | default(false)


def _probe_tasks() -> list[dict]:
    tasks = yaml.safe_load((REPO / "roles/pazny.thalamus/tasks/macos.yml").read_text(encoding="utf-8"))
    out = [t for t in tasks if "medulla_pulse_probe" in str(t.get("when", ""))]
    assert len(out) >= 2, f"the probe's tasks moved: {[t.get('name') for t in out]}"
    return out


def _visible() -> set[str]:
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity  # noqa: PLC0415
    names = set(nos_identity.default_config())
    names |= set(yaml.safe_load((REPO / "default.credentials.yml").read_text(encoding="utf-8")))
    names |= set(yaml.safe_load((REPO / "roles/pazny.thalamus/defaults/main.yml").read_text(encoding="utf-8")))
    tasks = yaml.safe_load((REPO / "roles/pazny.thalamus/tasks/macos.yml").read_text(encoding="utf-8"))
    names |= {t["register"] for t in tasks if isinstance(t, dict) and "register" in t}
    return names | ANSIBLE


class _Any(dict):
    """Ansible's filters and tests: the names only matter to Ansible, not to this gate."""

    def __missing__(self, key):
        return lambda *a, **k: None

    def __contains__(self, key):
        return True

    def get(self, key, default=None):
        return self[key]


def test_every_variable_the_probe_renders_is_visible():
    env, seen = jinja2.Environment(), _visible()
    env.filters, env.tests = _Any(env.filters), _Any(env.tests)
    used = set()
    for t in _probe_tasks():
        check = t.get("ansible.builtin.assert") or {}
        templated = [str(t.get("ansible.builtin.command")), str(t.get("environment")), str(check.get("fail_msg"))]
        bare = [str(c) for k in ("when", "failed_when") for c in ([t[k]] if isinstance(t.get(k), str) else t.get(k) or [])]
        bare += [str(check["that"])] if check.get("that") else []
        for s in templated + ["{{ " + b + " }}" for b in bare]:
            used |= jinja2.meta.find_undeclared_variables(env.parse(s))
    missing = sorted(v for v in used if v not in seen and v not in {"true", "false", "none"})
    assert not missing, f"the probe renders {missing}, defined nowhere pazny.thalamus can see"
