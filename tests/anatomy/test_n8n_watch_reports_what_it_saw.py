"""A watcher that looked at nothing must not read like one that found nothing.

MEASURED 2026-09-23. `n8n-pack.py watch` skipped every INACTIVE workflow with a
bare `continue` and exited 0 with no output. Both pack workflows were off, the
`ares-verify` Pulse clock had been POSTing their dead webhook twice a day
(HTTP 404, red since 2026-09-21), and the hourly watcher said nothing at all —
three runs of `rc=0` with an empty stdout_tail in `pulse_runs`.

This is the estate's signature defect in its cheapest form (a success marker
written by code that did not do the thing), and the gates that already exist
for it — test_post_wiring_is_not_self_reporting, test_backup_reaches_the_brain —
are the precedent for this one.

The tests drive `cmd_watch` against injected API responses: no live n8n, and
no reading of the source's prose about itself.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PACKS = REPO / "files" / "anatomy" / "n8n" / "packs"

_spec = importlib.util.spec_from_file_location("n8n_pack", REPO / "tools" / "n8n-pack.py")
N8N = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(N8N)


def _pack_ids() -> list[str]:
    return sorted(p["id"] for p in N8N.load_packs(PACKS))


def _run(monkeypatch, capsys, workflows, executions=None):
    """cmd_watch with the n8n API replaced by canned answers."""
    def fake_api(method, base, path, key, body=None):
        if path.startswith("/api/v1/workflows"):
            return 200, {"data": workflows}
        if path.startswith("/api/v1/executions"):
            return 200, {"data": executions or []}
        raise AssertionError(f"unexpected call {method} {path}")

    monkeypatch.setattr(N8N, "api", fake_api)
    monkeypatch.setattr(N8N, "read_secret", lambda *a, **k: "k")
    args = argparse.Namespace(packs=str(PACKS), url="http://x", secrets="/dev/null")
    rc = N8N.cmd_watch(args)
    return rc, capsys.readouterr()


def _live(pack_id: str, active: bool) -> dict:
    pack = next(p for p in N8N.load_packs(PACKS) if p["id"] == pack_id)
    return {"id": "w1", "name": N8N.load_workflow(pack)["name"], "active": active}


def test_there_are_packs_to_watch():
    """Positive control — an empty packs dir would satisfy everything below."""
    assert _pack_ids(), "no packs found; every assertion here would be vacuous"


def test_an_inactive_workflow_is_never_silent(monkeypatch, capsys):
    """The defect, as the thing that must stay false."""
    pid = _pack_ids()[0]
    rc, out = _run(monkeypatch, capsys, [_live(pid, active=False)] +
                   [_live(p, active=False) for p in _pack_ids()[1:]])
    said = out.out + out.err
    for p in _pack_ids():
        assert p in said, f"watch said nothing about {p} while it was inactive"
    assert "INACTIVE" in said


def test_an_inactive_workflow_someone_else_fires_is_a_finding(monkeypatch, capsys):
    """A Pulse clock aimed at a dead webhook can only ever 404 — that is not a
    pending operator decision, it is broken."""
    fired = [p["id"] for p in N8N.load_packs(PACKS) if N8N.pack_has_external_clock(p)]
    if not fired:
        pytest.skip("no pack currently carries an external Pulse clock")
    rc, out = _run(monkeypatch, capsys, [_live(p, active=False) for p in _pack_ids()])
    assert rc != 0, "an inactive workflow with a Pulse clock firing at it passed"
    assert any(p in out.err for p in fired)


def test_a_pack_n8n_never_heard_of_is_a_finding(monkeypatch, capsys):
    rc, out = _run(monkeypatch, capsys, [])
    assert rc != 0
    assert "ABSENT" in out.err


def test_an_active_healthy_workflow_passes(monkeypatch, capsys):
    """A detector that cannot report green is no detector."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rc, out = _run(monkeypatch, capsys,
                   [_live(p, active=True) for p in _pack_ids()],
                   executions=[{"status": "success", "stoppedAt": now}])
    assert rc == 0, out.err
    assert "active" in out.out


def test_the_external_clock_is_discovered_not_listed():
    """It must come from the manifests + the pack's own trigger nodes, so a new
    plugin cannot silently fall outside it."""
    src = (REPO / "tools" / "n8n-pack.py").read_text(encoding="utf-8")
    fn = src.split("def pack_has_external_clock", 1)[1].split("\ndef ", 1)[0]
    assert "plugins" in fn and "glob" in fn, "the clock check hardcodes its answer"
    assert json.dumps(sorted(N8N.pack_webhook_paths(
        next(p for p in N8N.load_packs(PACKS) if N8N.pack_webhook_paths(p))))), \
        "no pack declares a webhook path — the discovery would be vacuous"
