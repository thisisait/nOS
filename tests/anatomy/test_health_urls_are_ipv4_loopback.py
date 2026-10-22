"""A host-side health probe dials 127.0.0.1, never `localhost`.

Docker publishes a loopback port on 127.0.0.1 only. On Linux `localhost` resolves to ::1
first, nothing listens there, and the probe reads DOWN in ~20 ms. spark1 (2026-10-22):
Wing's hub reported traefik down while http://127.0.0.1:8082/ping answered 200
(manifest url_template http://localhost:{{ traefik_dashboard_port }}/ping).
"""
from pathlib import Path

import yaml

MANIFEST = Path(__file__).resolve().parents[2] / "state" / "manifest.yml"


def test_no_health_url_template_names_localhost():
    rows = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    rows = rows.get("services", rows) if isinstance(rows, dict) else rows
    bad = [r.get("id") for r in rows if isinstance(r, dict)
           and "//localhost" in str((r.get("health_check") or {}).get("url_template", ""))]
    assert not bad, f"health_check.url_template dials localhost (::1 first on Linux): {bad}"
