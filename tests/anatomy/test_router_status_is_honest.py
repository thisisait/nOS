"""Anatomy gate: the router reader must never report a green it did not measure.

`tools/router-status.py` reads a DECLARED fact file (`state/router.yml`) about
the estate's WAN router — a login-walled Mercusys BE3600 with no
unauthenticated status API (see `docs/router-as-estate-fact.md`). The one
thing this class of reader can get wrong, per house doctrine, is rendering
absence as agreement: reporting "forwards match" or "UPnP off" as if measured
when the router was never asked. This gate pins the two ways that could
happen: the missing-file case reporting a false green, and the declared
config leaking into the report as if it were a measurement.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "router-status.py"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(TOOL), *args],
        capture_output=True, text=True, timeout=30, cwd=REPO,
    )


def test_the_tool_exists_and_exits_zero() -> None:
    result = run("--json")
    assert result.returncode == 0, (
        "router-status.py must exit 0 like every other *-status.py reader — "
        "it reports, it does not gate"
    )


def test_the_declared_file_is_present_and_shaped() -> None:
    declared = REPO / "state" / "router.yml"
    assert declared.exists(), "state/router.yml is the declared-fact scaffolding this reader needs"
    import yaml
    data = yaml.safe_load(declared.read_text())["router"]
    for key in ("model", "gateway_ip", "admin_url", "firmware", "declared"):
        assert key in data, f"state/router.yml is missing declared field: {key}"
    assert {"remote_management_enabled", "upnp_enabled", "port_forwards"} <= set(data["declared"])


def test_missing_declared_file_reports_unknown_not_green() -> None:
    """The core refusal: no file, no verdict — UNKNOWN, never OK.

    The tool resolves state/router.yml relative to its own path (not cwd), so
    the only honest way to exercise "the file is gone" is to move it aside for
    the duration of one subprocess call.
    """
    declared = REPO / "state" / "router.yml"
    moved = declared.with_suffix(".yml.movedfortest")
    declared.rename(moved)
    try:
        result = run("--json")
    finally:
        moved.rename(declared)

    payload = json.loads(result.stdout)
    assert payload["status"] == "UNKNOWN", (
        "with state/router.yml absent, the tool must never report OK — "
        "that would be a green nothing measured"
    )
    assert result.returncode == 0


def test_measured_config_is_always_null() -> None:
    """The declared forwards/toggles must never be reported as measured.

    There is no credentialed path into this router (docstring, and
    docs/router-as-estate-fact.md §2/§4) — so `measured_config` staying `None`
    is not a TODO, it is the honest answer until that changes.
    """
    payload = json.loads(run("--json").stdout)
    assert payload["measured_config"] is None, (
        "measured_config went non-null — either a real measurement path was "
        "added (update this gate and the doctrine doc) or the reader started "
        "reporting the declared config as if it were measured"
    )
    assert "declared_config" in payload and payload["declared_config"] is not None


def test_human_output_labels_forwards_as_declared_not_measured() -> None:
    out = run().stdout
    assert "declared" in out and "measured" in out, (
        "the human-readable output must visibly distinguish declared intent "
        "from measured fact — collapsing them is the exact defect this gate exists to catch"
    )
    assert "none — no unauthenticated router API exists" in out
