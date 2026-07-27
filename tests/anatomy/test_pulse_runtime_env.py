"""Anatomy gate: Pulse must run the Python the repository pins, and reach Bone.

Two nightly-job defects, both invisible from a shell and both found by reading
run logs rather than by any test.

INTERPRETER. Every Python Pulse job is executed through its `#!/usr/bin/env
python3` shebang, so the first `python3` on the daemon's PATH *is* the runtime.
That PATH began with Homebrew's bin, which resolves to `python@3.14` — while
`.python-version` pins 3.13.13 and the operator's shell uses the pyenv shim. Jobs
with no third-party imports never noticed. `keap-features-sync` imports numpy and
failed every night with *"numpy not available on the host python"* while numpy
was installed all along, in the other interpreter. Measured 2026-07-27: with the
pinned directory first the same job succeeded on its first attempt
("upserted 2490 node features"), having never once succeeded before.

BONE'S PORT. Bone serves `/api/v1/notifications` on 8099 and verifies an HMAC.
Wing is 9000 and wants a Bearer. The gitleaks manifest named 9000, so every
nightly scan signed a notification, posted it to Wing, got 401, and logged
"findings ingested OK, audit only" — the findings went to Wing's API correctly on
9000 with the bearer, which is why nothing else looked wrong. Proven both ways on
2026-07-27: the same signed body returns 401 on 9000 and 200 on 8099.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
PLIST = REPO / "roles" / "pazny.pulse" / "templates" / "pulse.plist.j2"
PULSE_DEFAULTS = REPO / "roles" / "pazny.pulse" / "defaults" / "main.yml"
PLUGINS = REPO / "files" / "anatomy" / "plugins"
TOOLS = REPO / "tools"


def test_pulse_path_leads_with_the_pinned_interpreter() -> None:
    """The daemon's PATH must resolve `python3` to the pinned interpreter."""
    plist = PLIST.read_text()
    m = re.search(r"<key>PATH</key>\s*\n\s*<string>([^<]+)</string>", plist)
    assert m, "the Pulse plist no longer sets PATH — jobs would inherit launchd's bare default"
    path = m.group(1)
    first = path.split(":")[0]
    assert "pulse_python" in first, (
        "PATH must LEAD with the pinned interpreter's directory. It currently leads with "
        f"{first!r}, so `#!/usr/bin/env python3` resolves to whatever that directory ships — "
        "which is how a job importing numpy failed nightly while numpy was installed"
    )
    assert "pulse_python" in PULSE_DEFAULTS.read_text(), (
        "pulse_python is gone from the role defaults; the plist interpolates it"
    )


def test_no_pulse_job_points_at_wings_port_for_a_bone_route() -> None:
    """A Bone route on 9000 is Wing, and Wing answers an HMAC POST with 401."""
    offenders: list[str] = []
    for manifest in sorted(PLUGINS.glob("*/plugin.yml")):
        for ln, line in enumerate(manifest.read_text(errors="replace").splitlines(), 1):
            if "BONE" not in line.upper():
                continue
            if re.search(r":\s*9000\b", line) or "127.0.0.1:9000" in line:
                offenders.append(f"{manifest.parent.name}/plugin.yml:{ln} {line.strip()}")
    assert not offenders, (
        "a BONE_* endpoint points at 9000, which is Wing. Bone verifies the HMAC on "
        "/api/v1/notifications and lives on bone_port (8099); Wing returns 401 for a signed "
        "POST and the notification is silently downgraded to audit-only. Offenders:\n  "
        + "\n  ".join(offenders)
    )


def test_bone_fallbacks_agree_across_the_estate() -> None:
    """Every runner's BONE_API_URL fallback must name the same port.

    They already agreed — on 8099 — everywhere except the one script whose
    notification had been 401ing nightly. A lone disagreeing default is the shape
    this defect had, so it is the shape the gate watches for.
    """
    seen: dict[str, list[str]] = {}
    roots = [TOOLS, PLUGINS]
    for root in roots:
        for path in root.rglob("*.sh"):
            for ln, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                m = re.search(r"BONE_API_URL:-http://127\.0\.0\.1:(\d+)", line)
                if m:
                    seen.setdefault(m.group(1), []).append(f"{path.relative_to(REPO)}:{ln}")
    assert seen, "no BONE_API_URL fallbacks found — this gate is measuring nothing"
    assert len(seen) == 1, (
        "BONE_API_URL fallbacks disagree on the port; one of these is posting at the wrong "
        f"daemon: { {p: v for p, v in seen.items()} }"
    )
    assert "8099" in seen, f"the agreed fallback is not Bone's port: {list(seen)}"
