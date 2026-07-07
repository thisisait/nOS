"""Cycle-16 security hardening gates — pin the fixes so they can't silently regress.

- REM-107: Alloy's OTLP receiver must bind via `alloy_otlp_bind_addr` (loopback
  default), NOT `0.0.0.0` (Alloy is a host process → 0.0.0.0 = unauth LAN/Tailscale).
- REM-110: Bone's recon reads (services / status / health/aggregate) must be
  scope-gated; the O(1) /api/health liveness probe must stay ungated.
- qgis restart-loop: the compose entrypoint must pre-clean the stale symlink + pid
  file so a `restart:` recovers cleanly (idempotent).
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_alloy_otlp_binds_via_var_not_wildcard():
    for rel in (
        "files/anatomy/plugins/alloy-base/templates/config.alloy.j2",
        "files/observability/alloy/config.alloy.j2",
    ):
        src = (REPO / rel).read_text()
        assert "alloy_otlp_bind_addr" in src, f"{rel}: OTLP must bind via alloy_otlp_bind_addr"
        assert 'endpoint = "0.0.0.0:{{ alloy_otlp_grpc_port' not in src, f"{rel}: grpc still 0.0.0.0"
        assert 'endpoint = "0.0.0.0:{{ alloy_otlp_http_port' not in src, f"{rel}: http still 0.0.0.0"
    cfg = (REPO / "default.config.yml").read_text()
    assert "\nalloy_otlp_bind_addr: \"127.0.0.1\"" in cfg, "default must be loopback"


def test_bone_recon_endpoints_scope_gated_but_liveness_open():
    lines = (REPO / "files/anatomy/bone/main.py").read_text().splitlines()

    def defline(name: str) -> str:
        return next((l for l in lines if f"async def {name}(" in l), "")

    for handler in ("services", "status", "health_aggregate"):
        assert "require_scope" in defline(handler), f"Bone {handler}() must be scope-gated (REM-110)"
    # the liveness probe (docker healthcheck / launchd KeepAlive / smoke) stays open
    assert "require_scope" not in defline("health"), "/api/health liveness must stay ungated"


def test_qgis_entrypoint_guard_is_idempotent():
    src = (REPO / "roles/pazny.qgis_server/templates/compose.yml.j2").read_text()
    assert "entrypoint:" in src, "qgis needs the restart-loop entrypoint guard"
    assert "rm -f /etc/apache2/conf-enabled/qgis.conf" in src and "apache2.pid" in src, \
        "guard must pre-clean the stale symlink + pid file"
    assert 'exec /entrypoint.sh' in src, "guard must exec the original upstream entrypoint"
