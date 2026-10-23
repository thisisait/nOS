"""Once a host has its estate checkout, the playbook converges from it and nowhere else.

WHY (row estate-dev-split, 2026-10-23): `nos update` moves ~/.nos/estate, but a
converge started from the development tree (or a worktree of it) would still
re-point every persisted path (launchd plists, Pulse jobs, NOS_REPO_ROOT) back
at that tree. Preflight refuses it, names the command, and keeps one deliberate
escape. A host with no estate checkout (a fresh install, CI, a cloud session)
is not refused: it is told how to build one.

Shape gate over tasks/preflight-checkout-current.yml; the refusal's condition is
rendered with Jinja for the three cases.
"""
from __future__ import annotations

from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
PREFLIGHT = REPO / "tasks" / "preflight-checkout-current.yml"


def _tasks() -> list[dict]:
    return yaml.safe_load(PREFLIGHT.read_text(encoding="utf-8"))


def _named(fragment: str) -> dict:
    hits = [t for t in _tasks() if fragment in str(t.get("name", ""))]
    assert len(hits) == 1, f"expected one task named like {fragment!r}, found {len(hits)}"
    return hits[0]


def _holds(when: list[str], **ctx) -> bool:
    env = jinja2.Environment()
    env.filters["bool"] = lambda v: str(v).lower() in ("true", "1", "yes")
    env.filters["realpath"] = lambda v: str(Path(v).resolve())
    return all(env.from_string("{{ (" + w + ") | string }}").render(**ctx) == "True" for w in when)


def test_a_converge_outside_an_existing_estate_is_refused(tmp_path):
    refuse = _named("REFUSE: the estate converges from its own checkout")
    assert "ansible.builtin.fail" in refuse
    when = refuse["when"]
    est = tmp_path / "estate"
    (est / ".git").mkdir(parents=True)
    dev = tmp_path / "dev"
    dev.mkdir()
    base = dict(nos_estate_dir=str(est), _ckt_estate={"stat": {"exists": True}})
    assert _holds(when, playbook_dir=str(dev), **base), "a converge from the dev tree must be refused"
    assert not _holds(when, playbook_dir=str(est), **base), "a converge from the estate itself is the point"
    assert not _holds(when, playbook_dir=str(dev), allow_non_estate_checkout=True, **base), "the escape must work"
    assert not _holds(when, playbook_dir=str(dev), nos_estate_dir=str(est), _ckt_estate={"stat": {"exists": False}}), (
        "a host with no estate checkout is not refused")
    msg = str(refuse["ansible.builtin.fail"]["msg"])
    assert "nos update" in msg and "allow_non_estate_checkout" in msg, msg


def test_a_host_without_an_estate_is_told_how_to_build_one():
    hint = _named("No estate checkout yet")
    assert "estate-adopt.sh" in str(hint["ansible.builtin.debug"]["msg"])


def test_the_checks_run_always():
    for frag in ("REFUSE: the estate converges from its own checkout", "No estate checkout yet"):
        assert "always" in _named(frag).get("tags", []), frag
