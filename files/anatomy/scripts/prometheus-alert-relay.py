#!/usr/bin/env python3
"""Deliver Prometheus firing alerts to Bone. The link that was never built.

MEASURED 2026-08-05, and it is the reason this file exists:

    $ curl -s http://127.0.0.1:9090/api/v1/alerts | jq '.data.alerts | length'
    5
    $ curl -s http://127.0.0.1:9090/api/v1/status/config | grep -c 'alertmanager'
    0

Five `NosWarningServiceDegraded` alerts had been FIRING since 2026-07-26 — ten
days — for qdrant, gitea, firefly and two exporters. Six rule files evaluate on
schedule, complete with `runbook_url` annotations and severity labels, and
Prometheus has no `alerting:` block, so there is no Alertmanager and nothing
downstream of the evaluation. A curated alert corpus whose last link was never
connected.

This is the estate's recurring shape one floor up: the measurement is taken and
goes nowhere. Same week as `pulse_runs.duration_ms` (timed 17,254 times, stored
never) and the security drift gauge (written to a directory that does not exist).

WHY A RELAY AND NOT ALERTMANAGER. Alertmanager is the right answer for an estate
with paging rotations, silences and inhibition rules. This one already HAS a
notification spine — Bone's HMAC-signed `/api/v1/notifications`, the A9 severity
routing (`wing-inbox` | `ntfy` | `mail`), a digest, and a Wing inbox an operator
already reads. Adding a second delivery system beside it would give the estate
two answers to "where do alerts go", which is the defect this survey was looking
for, not a fix for it. So: one small poller, one existing spine.

WHAT IT DOES NOT DO, deliberately: no silences, no grouping, no inhibition. If
those become necessary, that is the signal to adopt Alertmanager properly rather
than to grow this file.

DELIVERY IS RECORDED BY THE DELIVERY, NOT BY THE ATTEMPT. The seen-state file
stores `delivered_at` only after Bone answers 2xx. A failed POST leaves the
alert unrecorded so the next run tries again — the alternative (stamping on
send) is exactly the "success marker written by the attempting code" defect this
estate has now found in four places.

EXIT CODES — and this one departs from the older watchers on purpose.
`drift-watch.sh` exits 0 unconditionally "because a watcher must not fail the
Pulse runner". That reasoning is how a watcher comes to report success while
delivering nothing. Here:

    0  polled successfully; everything that needed delivering was delivered
    1  Prometheus unreachable or unparseable — the poll did not happen
    2  at least one notification failed to reach Bone

A non-zero exit is the escalation path: Wing's `emitRunStateChangeNotification`
raises a HIGH "job failing" inbox row on the first failure of any pulse job, so
a relay that cannot deliver announces itself through the one channel that is
still working.

Env (the Pulse job supplies these):
    PROMETHEUS_URL            default http://127.0.0.1:9090
    BONE_API_URL              default http://127.0.0.1:8099   (9000 is WING)
    WING_EVENTS_HMAC_SECRET   Bone's HMAC seed; unset → report-only, exit 0
    ALERT_RELAY_STATE         default ~/.nos/prom-alerts-seen.json
    ALERT_RELAY_MIN_SEVERITY  info|low|medium|high|critical (default info)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROM_URL = os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9090").rstrip("/")
BONE_URL = os.environ.get("BONE_API_URL", "http://127.0.0.1:8099").rstrip("/")
SECRET = os.environ.get("WING_EVENTS_HMAC_SECRET", "")
STATE_PATH = Path(os.environ.get(
    "ALERT_RELAY_STATE", str(Path.home() / ".nos" / "prom-alerts-seen.json")))

#: Prometheus severity labels are free text; nOS's A9 ladder is fixed. Anything
#: unrecognised becomes `medium` rather than being dropped — an alert nobody
#: mapped is still an alert, and silently discarding it is the failure mode this
#: whole file exists to remove.
SEVERITY_MAP = {
    "critical": "critical", "high": "high", "error": "high",
    "warning": "medium", "medium": "medium",
    "info": "info", "low": "low", "none": "info",
}
RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
MIN_SEVERITY = os.environ.get("ALERT_RELAY_MIN_SEVERITY", "info").lower()

EXIT_OK = 0
EXIT_NO_POLL = 1
EXIT_UNDELIVERED = 2


def _log(msg: str) -> None:
    print(f"alert-relay: {msg}", flush=True)


def fetch_alerts() -> list[dict]:
    """Everything Prometheus currently considers an alert. Raises on failure."""
    req = urllib.request.Request(f"{PROM_URL}/api/v1/alerts",
                                 headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("status") != "success":
        raise ValueError(f"prometheus returned status={payload.get('status')!r}")
    return payload.get("data", {}).get("alerts", []) or []


def fingerprint(alert: dict) -> str:
    """Stable identity for one alert instance.

    Labels including the instance, so `NosWarningServiceDegraded` on qdrant and
    on gitea are two alerts rather than one that flaps between them. `activeAt`
    is deliberately EXCLUDED: an alert that goes pending→firing→pending should
    not re-notify on every transition.
    """
    labels = alert.get("labels", {}) or {}
    canonical = json.dumps(labels, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def load_state() -> dict:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE_PATH)


def notify(severity: str, title: str, body: str, metadata: dict) -> bool:
    """HMAC-signed POST to Bone. Mirrors drift-watch.sh's canonicalisation.

    Bone re-serialises with `json.dumps(sort_keys=True, separators=(',',':'))`
    before verifying, so the bytes signed here must already be in that form.
    """
    payload = {
        "severity": severity,
        "title": title,
        "body": body,
        "origin_plugin": "prometheus-alert-relay",
        "actor_id": "pulse:alert-relay",
        "actor_action_id": f"promalert-{int(time.time())}",
        "metadata": metadata,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ts = str(int(time.time()))
    sig = hmac.new(SECRET.encode("utf-8"),
                   f"{ts}.".encode("utf-8") + raw, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        f"{BONE_URL}/api/v1/notifications", data=raw, method="POST",
        headers={"Content-Type": "application/json",
                 "X-Wing-Timestamp": ts, "X-Wing-Signature": sig})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as exc:
        _log(f"POST /notifications HTTP {exc.code}: {exc.read()[:200]!r}")
    except (urllib.error.URLError, OSError) as exc:
        _log(f"cannot reach Bone at {BONE_URL}: {exc}")
    return False


def describe(alert: dict) -> tuple[str, str, str]:
    labels = alert.get("labels", {}) or {}
    ann = alert.get("annotations", {}) or {}
    name = labels.get("alertname", "UnnamedAlert")
    severity = SEVERITY_MAP.get(str(labels.get("severity", "")).lower(), "medium")
    target = labels.get("service") or labels.get("instance") or labels.get("job") or ""
    title = f"{name}{f' — {target}' if target else ''}"
    lines = [ann.get("summary") or ann.get("description") or "(no summary annotation)"]
    if ann.get("runbook_url"):
        lines.append(f"Runbook: {ann['runbook_url']}")
    since = alert.get("activeAt", "")
    if since:
        lines.append(f"Firing since {since}.")
    lines.append("Source: Prometheus rule evaluation, relayed by "
                 "files/anatomy/scripts/prometheus-alert-relay.py")
    return severity, title, "\n".join(lines)


def main() -> int:
    try:
        alerts = fetch_alerts()
    except Exception as exc:  # noqa: BLE001 — any poll failure is exit 1
        _log(f"cannot poll {PROM_URL}: {exc}")
        return EXIT_NO_POLL

    firing = [a for a in alerts if a.get("state") == "firing"]
    _log(f"{len(alerts)} alert(s) known, {len(firing)} firing")

    state = load_state()
    live = {fingerprint(a): a for a in firing}
    floor = RANK.get(MIN_SEVERITY, 0)
    undelivered = 0

    # RESOLVED first, and unconditionally — clearing a stale entry must not
    # depend on a notification succeeding, or a Bone outage would leave the
    # state file claiming alerts that stopped firing days ago.
    for key in [k for k in state if k not in live]:
        entry = state.pop(key)
        name = entry.get("title", key)
        if entry.get("delivered_at") and SECRET:
            if notify("info", f"RESOLVED: {name}",
                      f"This alert is no longer firing.\nWas first seen {entry.get('first_seen')}.",
                      {"fingerprint": key, "resolved": True}):
                _log(f"resolved: {name}")
            else:
                undelivered += 1

    for key, alert in live.items():
        entry = state.get(key)
        if entry and entry.get("delivered_at"):
            continue  # already reported and still firing — no repeat
        severity, title, body = describe(alert)
        if RANK.get(severity, 2) < floor:
            continue
        record = entry or {"first_seen": alert.get("activeAt") or _now_iso()}
        record["title"] = title
        record["severity"] = severity
        if not SECRET:
            _log(f"WOULD NOTIFY ({severity}) {title} — WING_EVENTS_HMAC_SECRET unset")
            state[key] = record
            continue
        if notify(severity, title, body,
                  {"fingerprint": key, "alertname": alert.get("labels", {}).get("alertname"),
                   "labels": alert.get("labels", {})}):
            record["delivered_at"] = _now_iso()
            _log(f"delivered ({severity}) {title}")
        else:
            undelivered += 1
            _log(f"UNDELIVERED ({severity}) {title} — will retry next run")
        state[key] = record

    save_state(state)
    if undelivered:
        _log(f"{undelivered} notification(s) did not reach Bone")
        return EXIT_UNDELIVERED
    return EXIT_OK


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    sys.exit(main())
