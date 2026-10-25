"""A converge refused as behind its upstream tells the estate clone to run `nos update`.

MEASURED 2026-10-25: the estate converges from ~/.nos/estate (branch `estate`), which moves with
`nos update`; the refusal still told the operator to run tools/deploy-sync.sh there, the dev
checkout's tool. Rendered from tasks/preflight-checkout-current.yml for both checkouts.
"""
from __future__ import annotations

from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]


def _message(ckt: list[str]) -> str:
    tasks = yaml.safe_load((REPO / "tasks/preflight-checkout-current.yml").read_text(encoding="utf-8"))
    fail = next(t for t in tasks if "behind its upstream" in t.get("name", ""))
    return jinja2.Environment().from_string(fail["ansible.builtin.fail"]["msg"]).render(
        _ckt=ckt, playbook_dir="/x", _ckt_fetch={"rc": 0})


def test_the_estate_clone_is_told_nos_update():
    m = _message(["OK", "estate", "origin/dev", "1", "0"])
    assert "nos update" in m and "deploy-sync" not in m, m


def test_a_dev_checkout_still_gets_deploy_sync():
    m = _message(["OK", "dev", "origin/dev", "1", "0"])
    assert "deploy-sync" in m and "nos update" not in m, m
