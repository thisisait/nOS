#!/usr/bin/env python3
"""grafana-check runner — one observability health digest per run (files/anatomy/loops/grafana-check.loop.yml).

Reads the firing Prometheus alerts (alert-relay's fetch_alerts) and the Loki error-line count over the
last 6 h, writes ~/.nos/loops/grafana-check/<UTC stamp>.json with the trend against the previous
digest, and posts ONE A9 note when the firing set changed. A source that does not answer is UNKNOWN in
the digest and suppresses the note (no storm when Prometheus is down). Exit 0 always: this reports.

    tools/loops/grafana-check.py            # run once
    tools/loops/grafana-check.py --dry      # digest to stdout, no file, no note
    tools/loops/grafana-check.py --trend    # the kept digests as a series: firing count, Loki errors
    tools/loops/grafana-check.py --selftest # offline

Env: PROMETHEUS_URL, LOKI_URL (default http://127.0.0.1:3100), BONE_API_URL, WING_EVENTS_HMAC_SECRET,
GRAFANA_CHECK_DIR (default ~/.nos/loops/grafana-check), GRAFANA_CHECK_KEEP_DAYS (default 30: older
digests are pruned after each run, the newest never, since the next run compares against it).
"""

from __future__ import annotations

import calendar
import hashlib
import hmac
import importlib.util
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("relay", REPO / "files/anatomy/scripts/prometheus-alert-relay.py")
relay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(relay)

LOKI = os.environ.get("LOKI_URL", "http://127.0.0.1:3100").rstrip("/")
DIR = Path(os.environ.get("GRAFANA_CHECK_DIR") or Path.home() / ".nos" / "loops" / "grafana-check")
KEEP_DAYS = int(os.environ.get("GRAFANA_CHECK_KEEP_DAYS") or 30)
STAMP = "%Y-%m-%dT%H%M%SZ"
ERRORS_Q = 'sum(count_over_time({job=~".+"} |~ "(?i)(level=error|\\"level\\":\\"error\\")" [6h]))'


def firing() -> list[str] | None:
    try:
        alerts = relay.fetch_alerts()
    except Exception:  # noqa: BLE001 — any failure is UNKNOWN, said in the digest
        return None
    return sorted({(a.get("labels") or {}).get("alertname", "?") for a in alerts if a.get("state") == "firing"})


def loki_errors() -> int | None:
    url = f"{LOKI}/loki/api/v1/query?" + urllib.parse.urlencode({"query": ERRORS_Q})
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            res = (json.loads(r.read()).get("data") or {}).get("result") or []
    except Exception:  # noqa: BLE001
        return None
    return int(float(res[0]["value"][1])) if res else 0


def digest(now: str, fire: list[str] | None, errors: int | None, prev: dict | None) -> dict:
    before = (prev or {}).get("firing")
    d = {"at": now, "firing": fire, "firing_state": "UNKNOWN" if fire is None else "OK",
         "loki_errors_6h": errors, "loki_state": "UNKNOWN" if errors is None else "OK",
         "previous_at": (prev or {}).get("at")}
    if fire is not None and isinstance(before, list):
        d["started"] = sorted(set(fire) - set(before))
        d["stopped"] = sorted(set(before) - set(fire))
        d["changed"] = bool(d["started"] or d["stopped"])
    else:
        d["changed"] = False   # no comparison without both sides: no note, no storm
    return d


def note(d: dict) -> bool:
    title = f"Observability: {len(d['firing'])} firing — +{len(d['started'])} / -{len(d['stopped'])} since the last digest"
    body = "\n".join([f"started: {', '.join(d['started']) or '-'}", f"stopped: {', '.join(d['stopped']) or '-'}",
                      f"Loki error lines (6 h): {d['loki_errors_6h'] if d['loki_errors_6h'] is not None else 'UNKNOWN'}"])
    return post({"severity": "medium" if d["started"] else "info", "title": title, "body": body,
                 "origin_plugin": "loop:grafana-check", "actor_id": "pulse:loop:grafana-check",
                 "supersede_key": "grafana-check-digest", "metadata": {"started": d["started"], "stopped": d["stopped"]}})


def post(payload: dict) -> bool:
    """One signed A9 note to Bone; False when there is no secret or Bone does not take it. ops-digest.py posts through it too."""
    secret = os.environ.get("WING_EVENTS_HMAC_SECRET", "")
    if not secret:
        return False
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    req = urllib.request.Request(f"{relay.BONE_URL}/api/v1/notifications", data=raw, method="POST",
                                 headers={"Content-Type": "application/json", "X-Wing-Timestamp": ts, "X-Wing-Signature": sig})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status in (200, 201)
    except Exception:  # noqa: BLE001
        return False


def previous() -> dict | None:
    files = sorted(DIR.glob("*.json")) if DIR.is_dir() else []
    for f in reversed(files):
        try:
            return json.loads(f.read_text())
        except (OSError, ValueError):
            continue
    return None


def _stamped(d: Path) -> list[tuple[float, Path]]:
    """(epoch, file) of each digest named by its UTC stamp, oldest first; another name is not ours."""
    out = []
    for f in d.glob("*.json") if d.is_dir() else []:
        try:
            out.append((calendar.timegm(time.strptime(f.stem, STAMP)), f))
        except ValueError:
            continue
    return sorted(out)


def prune(d: Path, now: float, keep_days: int = KEEP_DAYS) -> int:
    """Deletes stamped digests older than keep_days; the newest stays whatever its age."""
    files = _stamped(d)
    old = [f for t, f in files[:-1] if now - t > keep_days * 86400]
    for f in old:
        f.unlink(missing_ok=True)
    return len(old)


def trend(d: Path) -> list[dict]:
    """The kept digests as a series: when, how many alerts fired, Loki error lines; None = UNKNOWN."""
    rows = []
    for _, f in _stamped(d):
        try:
            g = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        fire = g.get("firing")
        rows.append({"at": g.get("at"), "firing": len(fire) if isinstance(fire, list) else None,
                     "loki_errors_6h": g.get("loki_errors_6h"), "started": g.get("started") or []})
    return rows


def print_trend(rows: list[dict]) -> None:
    if not rows:
        print(f"grafana-check: no digests in {DIR}")
        return
    top = max([r["firing"] for r in rows if r["firing"] is not None] or [1]) or 1
    for r in rows:
        n = r["firing"]
        bar = "?" if n is None else "#" * round(20 * n / top)
        loki = "UNKNOWN" if r["loki_errors_6h"] is None else r["loki_errors_6h"]
        new = f"  +{', '.join(r['started'])}" if r["started"] else ""
        print(f"{r['at']}  firing {'?' if n is None else n:>3} {bar:<20}  loki errors {loki}{new}")


def selftest() -> int:
    a = digest("t2", ["A", "B"], 3, {"at": "t1", "firing": ["B", "C"]})
    assert (a["started"], a["stopped"], a["changed"]) == (["A"], ["C"], True), a
    assert digest("t2", ["B"], 0, {"firing": ["B"]})["changed"] is False
    u = digest("t2", None, None, {"firing": ["B"]})
    assert u["firing_state"] == "UNKNOWN" and u["changed"] is False and "started" not in u, u
    assert digest("t1", ["A"], 1, None)["changed"] is False   # first run: no note
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        d, now = Path(t), time.time()
        for age, fire in ((40, ["A"]), (10, None), (0, ["A", "B"])):
            stamp = time.strftime(STAMP, time.gmtime(now - age * 86400))
            (d / f"{stamp}.json").write_text(json.dumps({"at": stamp, "firing": fire, "loki_errors_6h": age}))
        (d / "notes.json").write_text("{}")   # not a stamped digest: never touched
        assert [r["firing"] for r in trend(d)] == [1, None, 2]
        assert prune(d, now, 30) == 1 and len(_stamped(d)) == 2 and (d / "notes.json").exists()
        assert prune(d, now + 400 * 86400, 30) == 1 and len(_stamped(d)) == 1   # the newest always stays
    print("selftest OK: trend, unchanged, UNKNOWN suppresses the note, first run quiet, prune keeps the newest")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--trend" in sys.argv:
        print_trend(trend(DIR))
        return 0
    now = time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())
    d = digest(now, firing(), loki_errors(), previous())
    if "--dry" in sys.argv:
        print(json.dumps(d, indent=2))
        return 0
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{now}.json").write_text(json.dumps(d, indent=2) + "\n")
    sent = note(d) if d["changed"] else None
    pruned = prune(DIR, time.time())
    print(f"grafana-check: {d['firing_state']} firing={len(d['firing'] or [])} loki={d['loki_state']} "
          f"changed={d['changed']} note={'sent' if sent else 'not sent' if sent is False else 'none'} pruned={pruned}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
