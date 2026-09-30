"""An api_calls `when:` is evaluated with Ansible's filters.

load_plugins._eval_condition built a bare Jinja environment, so the most
common condition — `install_x | bool` — raised "No filter named 'bool'";
the plugin went degraded and its post_compose API calls never ran
(gitea-base, nextcloud-base, portainer-base; surfaced 2026-09-30 once
degraded plugins were printed).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))
import load_plugins as lp  # noqa: E402


def test_bool_filter_in_a_condition():
    assert lp._eval_condition("install_authentik | bool", {}, {"install_authentik": "true"}) is True
    assert lp._eval_condition("install_authentik | bool", {}, {"install_authentik": "false"}) is False


def test_registers_and_filters_together():
    regs = {"_nc": {"state": "running"}}
    assert lp._eval_condition("_nc.state == 'running' and (flag | bool)", regs, {"flag": "yes"}) is True


def test_every_declared_condition_evaluates():
    """Every `when:` in every plugin hook file evaluates without raising."""
    import yaml
    for f in sorted((REPO / "files/anatomy/plugins").glob("*/hooks/*.yml")):
        for call in yaml.safe_load(f.read_text()) or []:
            if isinstance(call, dict) and call.get("when"):
                lp._eval_condition(str(call["when"]), {}, {})   # StrictUndefined → False, never raise
