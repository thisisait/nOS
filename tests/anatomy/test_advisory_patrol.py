"""The advisory patrol keeps what it found, and red-status says it.

Row advisory-patrol: tools/advisory-status.py is a reader the operator had to
remember to run (2026-10-23, FrankenPHP: two days on a high advisory). The
patrol runs it nightly from Pulse, keeps the report in ~/.nos/advisory/last.json
and exits with the verdict; red-status reads that file. A match the operator
judged (state/genome/advisory-judgements.yml, id + subject, with an until date)
stops being red until the date; an expired judgement is red again.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


adv = _load("advisory_status", "advisory-status.py")
patrol = _load("advisory_patrol", "advisory-patrol.py")
red = _load("red_status", "red-status.py")

TODAY = datetime(2026, 10, 24, tzinfo=timezone.utc).date()


def _rep(*, pins=(), locks=(), unknown=False) -> dict:
    src = {"github": {"state": "UNKNOWN" if unknown else "OK", "asked": 1, "errors": []},
           "osv": {"state": "OK", "asked": 1, "errors": []}, "cve.now": {"state": "OK", "asked": 1, "errors": []}}
    return {"verdict": "AFFECTED", "sources": src, "counts": {},
            "pins": [{"var": v, "version": ver, "state": "affected", "matches": ms} for v, ver, ms in pins],
            "lockfiles": [{"organ": o, "state": "affected", "matches": ms} for o, ms in locks]}


def _m(i, sev, kev=False, fixed="9.9", package=None):
    return {"id": i, "severity": sev, "kev": kev, "fixed": fixed, **({"package": package} if package else {})}


def test_serious_is_high_critical_or_kev():
    rep = _rep(pins=[("apex_version", "1.30.6", [_m("A", 8.1), _m("B", 6.5), _m("C", 3.0, kev=True)])],
               locks=[("cortex", [_m("D", "HIGH", package="zod"), _m("E", "MODERATE", package="qs")])])
    got = {(u["subject"], u["id"]) for u in adv.unjudged(rep, {}, TODAY)}
    assert got == {("apex_version", "A"), ("apex_version", "C"), ("cortex:zod", "D")}, got


def test_a_judgement_in_force_silences_only_its_subject(tmp_path):
    f = tmp_path / "j.yml"
    f.write_text("judgements:\n"
                 "  - {id: A, subject: apex_version, verdict: accepted, reason: r, until: 2026-11-30}\n"
                 "  - {id: D, subject: cortex:zod, verdict: not-applicable, reason: r, until: 2026-10-01}\n")
    rep = _rep(pins=[("apex_version", "1", [_m("A", 9.0)]), ("other_version", "1", [_m("A", 9.0)])],
               locks=[("cortex", [_m("D", "HIGH", package="zod")])])
    got = {(u["subject"], u["id"]) for u in adv.unjudged(rep, adv.judgements(f), TODAY)}
    assert got == {("other_version", "A"), ("cortex:zod", "D")}, got


def test_the_committed_judgements_parse():
    for j in adv.judgements().values():
        assert j["verdict"] in ("accepted", "not-applicable") and j.get("reason") and j.get("until"), j


def test_patrol_keeps_the_report_and_exits_with_the_verdict(tmp_path, monkeypatch):
    snap = tmp_path / "advisory" / "last.json"
    monkeypatch.setattr(patrol, "SNAPSHOT", snap)
    monkeypatch.setattr(patrol, "_github_token", lambda: None)
    cases = [(_rep(pins=[("x_version", "1", [_m("A", 9.8)])]), 1),
             (_rep(unknown=True), 2),
             (_rep(), 0)]
    for rep, code in cases:
        monkeypatch.setattr(patrol.adv, "collect", lambda rep=rep, **_: rep)
        assert patrol.main([]) == code
        kept = json.loads(snap.read_text())
        assert kept["at"] and kept["verdict"] == rep["verdict"]
    assert oct(snap.stat().st_mode)[-3:] == "600"


def test_red_status_names_unjudged_matches_and_a_stale_patrol(tmp_path, monkeypatch):
    snap = tmp_path / "last.json"
    monkeypatch.setattr(red, "ADVISORY_SNAPSHOT", snap)
    assert red.advisories() is None  # absent = UNKNOWN, never green

    rep = _rep(pins=[("apex_version", "1.30.6", [_m("CVE-1", 8.1, fixed="1.31.2")])])
    rep["at"] = datetime.now(timezone.utc).isoformat()
    snap.write_text(json.dumps(rep))
    lines = red.reds({"advisories": red.advisories()})
    assert any("apex_version" in ln and "CVE-1" in ln for ln in lines), lines

    rep["at"] = (datetime.now(timezone.utc) - timedelta(hours=40)).isoformat()
    snap.write_text(json.dumps(rep))
    assert any("advisory patrol stale" in ln for ln in red.reds({"advisories": red.advisories()}))
