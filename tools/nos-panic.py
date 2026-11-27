#!/usr/bin/env python3
"""`nos panic`: what a panic would cut at the edge right now; on the operator's --confirm, cut exactly that.

Row immune-panic-mode, ruled 2026-11-23 (b). An effector the operator arms, never a model or the loop.

  nos panic [--plan]    the plan: every KEV-listed or CRITICAL advisory match no judgement covers, on an
                        app with a manifest router, with the sanction plan and its lift line. Writes nothing.
  nos panic --confirm   for each planned app, tools/nos-sanction.py <id> --level edge --confirm (its main(),
                        no shell), one at a time; the lift line for each; the sanctions in force.

Matches come from the advisory patrol's kept report (tools/advisory-status.py JSON, ~/.nos/advisory/last.json,
NOS_ADVISORY_SNAPSHOT) and the judgements file; ids from the manifest only. A report that is missing, broken
or blind prints UNKNOWN and arms nothing (never "nothing to do"); a report older than 48 h arms nothing.
The door is never cut: authentik, traefik, wing and the face (a cut there locks the operator out).
Level edge only: no container is stopped. A sanction lifts with the printed line, never by itself.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

SNAPSHOT = pathlib.Path(os.environ.get("NOS_ADVISORY_SNAPSHOT") or pathlib.Path.home() / ".nos" / "advisory" / "last.json")
DOOR = ("authentik", "traefik", "wing", "face")
MAX_AGE = timedelta(hours=48)


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def critical(m: dict) -> bool:
    """KEV-listed, or CRITICAL by name or CVSS >= 9.0. HIGH alone never panics (the ruling's floor)."""
    s = m.get("severity")
    if m.get("kev") is True:
        return True
    if isinstance(s, (int, float)):
        return s >= 9.0
    return str(s).upper() == "CRITICAL"


def report(now: datetime) -> tuple[dict | None, str | None]:
    """(the kept report, None) or (None, why it is UNKNOWN)."""
    try:
        rep = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"no advisory report at {SNAPSHOT} (tools/advisory-patrol.py writes it)"
    except (OSError, ValueError) as exc:
        return None, f"advisory report {SNAPSHOT} unreadable ({type(exc).__name__})"
    if not isinstance(rep, dict) or rep.get("error") or not isinstance(rep.get("pins"), list):
        return None, f"advisory report {SNAPSHOT} holds no reading ({(rep or {}).get('error', 'no pins')})"
    try:
        at = datetime.fromisoformat(str(rep.get("at")))
    except ValueError:
        return None, f"advisory report {SNAPSHOT} has no time it was read"
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    if now - at > MAX_AGE:
        return None, f"advisory report read {at:%Y-%m-%d %H:%M} UTC is older than 48 h (tools/advisory-patrol.py)"
    return rep, None


def rendered(sanction) -> set[str] | None:
    """The sanction-<router> middlewares pazny.traefik rendered (one per deployed router), or None if unreadable."""
    import yaml
    try:
        doc = yaml.safe_load(sanction.dynamic_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    mw = ((doc or {}).get("http") or {}).get("middlewares")
    return set(mw) if isinstance(mw, dict) else None


def targets(rep: dict, now: datetime, routers: set[str], router) -> tuple[dict, list[str]]:
    """(app id -> its matches, the lines for matches that are not cut and why). Only an app whose
    sanction middleware is rendered is cut: nos-sanction writes its record before the cut, so a cut
    that cannot land would leave a sanction nobody can lift until traefik renders that router."""
    adv = _load("advisory_status", "advisory-status.py")
    rows = {r["version_var"]: r for r in ni.services() if r.get("version_var")}
    cut: dict[str, list[dict]] = {}
    held: list[str] = []
    for u in adv.unjudged(rep, adv.judgements(), now.date()):
        if not critical(u):
            continue
        row = rows.get(u["subject"])
        what = f"{u['subject']} {u['version']} {u['id']}"
        if row is None:
            held.append(f"not cut   {what}: no manifest row pins it (an organ or a sidecar)")
        elif row["id"] in DOOR:
            held.append(f"not cut   {what}: {row['id']} is the door; a cut there locks the operator out")
        elif not (row.get("domain_var") and row.get("port_var")):
            held.append(f"not cut   {what}: {row['id']} has no router")
        elif f"sanction-{router(row['id'])}" not in routers:
            held.append(f"not cut   {what}: {row['id']} has no rendered router (not installed, or traefik not converged)")
        else:
            cut.setdefault(row["id"], []).append(u)
    order = sorted(cut, key=lambda a: (not any(m.get("kev") is True for m in cut[a]), a))
    return {a: cut[a] for a in order}, held


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--plan", action="store_true", help="the default: show, write nothing")
    ap.add_argument("--confirm", action="store_true", help="arm the edge sanctions (the operator's act)")
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    rep, why = report(now)
    if why:
        print(f"UNKNOWN: {why}; nothing armed")
        return 0 if not a.confirm else 1
    blind = sorted(n for n, s in (rep.get("sources") or {}).items() if s.get("state") == "UNKNOWN")
    sanction = _load("nos_sanction", "nos-sanction.py")
    routers = rendered(sanction)
    if routers is None:
        print(f"UNKNOWN: {sanction.dynamic_file()} is not rendered (nos --tags traefik); nothing armed")
        return 0 if not a.confirm else 1
    cut, held = targets(rep, now, routers, sanction.router)
    in_force = sanction.load_record()
    print(f"panic — report read {rep['at']}" + (f"; sources blind: {', '.join(blind)}" if blind else ""))
    for line in held:
        print(line)
    if not cut:
        print(f"UNKNOWN: no KEV or CRITICAL match found, but {', '.join(blind)} unreadable; nothing armed"
              if blind else "nothing to do: no unjudged KEV or CRITICAL match on an app with a router")
        return 1 if (blind and a.confirm) else 0
    failed = 0
    for app, ms in cut.items():
        reason = ", ".join(sorted({str(m["id"]) for m in ms}))
        for m in ms:
            print(f"match     {app}: {m['id']} {m.get('severity') or '?'} kev {m.get('kev')} "
                  f"on {m['subject']} {m['version']}, fixed {m.get('fixed') or 'none published'}")
        if app in in_force:
            print(f"  already sanctioned since {in_force[app].get('at')}; lift: tools/nos-sanction.py {app} --lift --confirm")
            continue
        args = [app, "--level", "edge", "--reason", reason] + (["--confirm"] if a.confirm else [])
        try:
            rc = sanction.main(args)
        except SystemExit as exc:          # apply_edge refuses when the router's middleware is not rendered
            print(f"  cut FAILED: {exc}" + ("; the record holds it, so the next traefik converge renders the cut"
                                           if a.confirm else ""))
            rc = 1
        failed += rc != 0
        print(f"  lift: tools/nos-sanction.py {app} --lift --confirm")
    if a.confirm:
        sanction.main(["--list"])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
