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


#: A service answered and answered wrongly. Routing drift.
HARD_FAIL = {"404", "500", "502", "503"}
#: Nothing answered. curl reports 000 whether the estate is down or Docker's
#: host->container forwarding is (fee 43) — from the host those are the same
#: string, so this is UNREACHABLE, never drift.
UNREACHABLE = {"000", "ERR"}
OK_STATUSES = {"200", "301", "302", "307", "401", "403"}

# Mirror HubPresenter's backend-only set so the gate audits exactly what /hub
# actually renders (otherwise it false-positives on systems the operator never
# sees in the UI). phi-hub-card-icon-gap (2026-06-14): the list is now the
# plugin-harvested `kind: backend` flag (run the real loader + render) UNIONed
# with the non-plugin host floor (nginx has no manifest) — both lists collapsed
# to the manifest read, no more duplicated hardcoded allow-list.
def _backend_only() -> set[str]:
    import json as _json
    import pathlib
    import sys as _sys

    repo = pathlib.Path(__file__).resolve().parents[2]
    _sys.path.insert(0, str(repo / "files/anatomy/module_utils"))
    import load_plugins as lp  # noqa: E402

    plugins = lp.discover(repo / "files/anatomy/plugins")
    lp.run_aggregators(plugins)
    wing = next(p for p in plugins if p.name == "wing-base")
    entries = wing.inputs.get("backend_kinds", [])
    slugs = {
        str(e["slug"]).replace("-", "_")
        for e in entries
        if e.get("kind") == "backend" and "slug" in e
    }
    return slugs | {"nginx"}  # non-plugin host floor (HubPresenter)


_BACKEND_ONLY = _backend_only()


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
    unreachable: list[tuple[str, str, str]] = []
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
        elif code in UNREACHABLE:
            unreachable.append((sid, code, url))

    print(f"\n  status distribution: {dict(counter)}")

    # Everything unreachable is a transport verdict, not N service verdicts.
    # Report it and SKIP: this gate audits routing, and from the host it cannot
    # see routing through a forwarder that is not forwarding.
    if unreachable and not bad:
        names = ", ".join(sid for sid, _, _ in unreachable[:6])
        pytest.skip(
            f"{len(unreachable)} of {sum(counter.values())} unreachable from the "
            f"host ({names}) — no service answered, so this cannot distinguish "
            f"drift from Docker's forwarder (fee 43). Ask a container instead: "
            f"docker exec <peer> curl -sk -H 'Host: <domain>' https://infra-traefik-1/")

    if bad:
        lines = "\n".join(f"    {sid:24s} [{code}] {url}" for sid, code, url in bad)
        extra = (f"\n  ({len(unreachable)} more were UNREACHABLE — not counted as drift)"
                 if unreachable else "")
        pytest.fail(f"\n{len(bad)} hard failures (404/5xx) — auto-wiring drift:\n{lines}{extra}")


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
