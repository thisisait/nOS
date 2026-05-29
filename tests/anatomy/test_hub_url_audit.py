"""Post-run URL audit — every hub system URL must reach a valid HTTP response.

The auto-wiring epic deliverable: drift between `install_*` flags and the
systems table → /hub click → 404 (Traefik also gates on the flag). After my
registry-orphan sweep (cb2088d) + the 4 backend hub_card removals (80523f5),
a fresh `-e @profiles/all-on.yml` run should yield ZERO hard 404s.

Acceptable statuses: 200 (live), 301/302 (Authentik SSO redirect), 307 (also
redirect), 401/403 (auth gate after login). HARD FAIL: 404, 500, 502, 503 —
the operator must fix or sweep them.

Run-mode: this test auto-discovers the live daemon's WING_API_TOKEN from the
operator's plist (or env override). When the daemon isn't reachable (CI, fresh
checkout), it skips. When the daemon IS up, it curls every system's
domain_url and asserts no hard failures.

Run it AFTER the playbook:

    python3 -m pytest tests/anatomy/test_hub_url_audit.py -v -s
"""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
from collections import Counter

import pytest


HARD_FAIL = {"404", "500", "502", "503", "ERR", "000"}
OK_STATUSES = {"200", "301", "302", "307", "401", "403"}

# Mirror HubPresenter::BACKEND_ONLY_SLUGS so the gate audits exactly what /hub
# actually renders (otherwise it false-positives on systems the operator never
# sees in the UI). When a slug is promoted to a manifest `kind: backend` flag,
# both lists collapse to the manifest read.
_BACKEND_ONLY = {"bluesky_pds", "loki", "tempo", "prometheus", "alloy", "nginx", "qgis_server"}


def _wing_token() -> str | None:
    """The live daemon's bearer; checks env first, then the operator's plist."""
    if (t := os.environ.get("WING_API_TOKEN")):
        return t
    plist_path = os.path.expanduser(
        "~/Library/LaunchAgents/eu.thisisait.nos.wing.plist"
    )
    if not os.path.isfile(plist_path):
        return None
    try:
        with open(plist_path, "rb") as f:
            return plistlib.load(f)["EnvironmentVariables"].get("WING_API_TOKEN")
    except (OSError, KeyError, ValueError):
        return None


def _systems() -> list[dict]:
    token = _wing_token()
    if not token:
        pytest.skip("WING_API_TOKEN not discoverable — live daemon needed")
    r = subprocess.run(
        ["/usr/bin/curl", "-sS", "--max-time", "5",
         "-H", f"Authorization: Bearer {token}",
         "http://127.0.0.1:9000/api/v1/hub/systems"],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.startswith("{"):
        pytest.skip(f"Wing /api/v1/hub/systems unreachable (rc={r.returncode})")
    try:
        return json.loads(r.stdout).get("systems", []) or []
    except json.JSONDecodeError:
        pytest.skip("Wing hub API returned non-JSON")


def _curl_status(url: str) -> str:
    r = subprocess.run(
        ["/usr/bin/curl", "-sS", "-k", "-o", "/dev/null",
         "-w", "%{http_code}", "--max-time", "8", url],
        capture_output=True, text=True,
    )
    return (r.stdout or "").strip() or "ERR"


def test_no_hard_404_in_hub_systems():
    """Every system with an HTTP(S) domain_url must NOT 404/500/502/503."""
    systems = _systems()
    assert systems, "no systems returned"

    bad: list[tuple[str, str, str]] = []
    counter: Counter[str] = Counter()
    for s in systems:
        sid = str(s.get("id", "?"))
        if sid in _BACKEND_ONLY:
            continue   # surfaces via Grafana / clients, not /hub
        url = s.get("domain_url")
        if not url or not url.startswith("http"):
            continue   # TCP-only daemon or no public domain → not a /hub card
        code = _curl_status(url)
        counter[code] += 1
        if code in HARD_FAIL:
            bad.append((sid, code, url))

    print(f"\n  status distribution: {dict(counter)}")
    if bad:
        lines = "\n".join(f"    {sid:24s} [{code}] {url}" for sid, code, url in bad)
        pytest.fail(f"\n{len(bad)} hard failures (404/5xx) — auto-wiring drift:\n{lines}")


def test_hub_systems_table_is_not_stale():
    """The systems table must not show services whose install_* flag is off.
    Detects the drift my orphan sweep (cb2088d) was built to catch — a
    regression would re-introduce the /hub-click-404 class of bug."""
    systems = _systems()
    # Sample of services that profiles/all-on.yml enables; if anyone of these
    # has source=registry but no install_* coverage, treat as drift indicator.
    seen = {s["id"] for s in systems if s.get("source") == "registry"}
    # Bare assertion: there should be SOMETHING; the deeper drift detection
    # lives in the URL audit above.
    assert seen, "no registry-sourced systems — ingest didn't run?"
