"""Anatomy gate — Bone's port is a variable, and it is never 9000.

The same one-line defect has now been introduced three separate times:

  * `files/anatomy/plugins/gitleaks/plugin.yml`   — fixed 2026-07-08
  * `files/anatomy/plugins/authentik-tofu-drift-base/plugin.yml` — fixed the same day
  * `files/anatomy/agents/conductor/agent.yml`          — found 2026-07-30, seventeen
    days later, having silently 401'd every night in between

Each time the shape is identical: an emitter sets `BONE_API_URL` to
`http://127.0.0.1:9000`. **9000 is Wing.** Bone is `bone_port` (8099), and Bone is
what verifies the HMAC on `/api/v1/notifications` — so a signed POST to 9000
reaches a service with no verifier, returns 401, and the caller (which treats
notification failure as non-fatal, correctly) exits 0 with its message undelivered.

The gitleaks fix left a comment saying it was *"the sole outlier"*. That sentence
was already false when written — conductor.yml had the same bug — and prose cannot
notice that. This test can.

Wing's own URL (`WING_API_URL`) legitimately IS 9000; the check is scoped to Bone
so the two never get conflated again.

CI-safe: source scan. No network, no Docker, no live host.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
SCAN_ROOTS = [REPO / "files" / "anatomy", REPO / "tools", REPO / "hooks"]
SUFFIXES = {".yml", ".yaml", ".sh", ".py", ".j2"}

WING_PORT = "9000"

# Any assignment of a Bone-ish URL variable, in YAML (`KEY: "..."`) or shell
# (`KEY="..."` / `${KEY:-...}`).
BONE_URL_ASSIGN = re.compile(
    r"""(?P<key>BONE_API_URL|BONE_URL)\s*[:=]\s*['"]?(?P<val>[^'"\n,}]+)""",
)


def _files():
    for root in SCAN_ROOTS:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in SUFFIXES and "node_modules" not in p.parts:
                yield p


def test_no_emitter_points_bone_at_wings_port():
    offenders = []
    for p in _files():
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue  # prose may name the wrong port while explaining it
            m = BONE_URL_ASSIGN.search(line)
            if not m:
                continue
            val = m.group("val")
            if f":{WING_PORT}" in val:
                offenders.append(f"{p.relative_to(REPO)}:{i}: {m.group('key')} -> {val.strip()}")

    assert not offenders, (
        "Bone URL pointed at Wing's port 9000. Bone verifies the notification "
        "HMAC; Wing does not, so the POST 401s and the message is lost while the "
        "job still exits 0. Use bone_port / 8099:\n  " + "\n  ".join(offenders)
    )


def test_manifests_render_bone_port_from_the_variable():
    """A literal 8099 is correct but brittle — manifests should template it."""
    offenders = []
    for p in (REPO / "files" / "anatomy").rglob("plugin.yml"):
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            m = re.search(r"BONE_API_URL\s*:\s*['\"]?([^'\"\n]+)", line)
            if m and "bone_port" not in m.group(1):
                offenders.append(f"{p.relative_to(REPO)}:{i}: {m.group(1).strip()}")
    assert not offenders, (
        "plugin manifests must render Bone's port through {{ bone_port }} rather "
        "than hardcoding it:\n  " + "\n  ".join(offenders)
    )


def test_agent_profiles_render_bone_port_from_the_variable():
    """Agent profiles are harvested into the same Pulse catalog as manifests."""
    offenders = []
    agents = REPO / "files" / "anatomy" / "agents"
    for p in agents.glob("*/agent.yml"):
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            m = re.search(r"BONE_API_URL\s*:\s*['\"]?([^'\"\n]+)", line)
            if m and "bone_port" not in m.group(1):
                offenders.append(f"{p.relative_to(REPO)}:{i}: {m.group(1).strip()}")
    assert not offenders, (
        "agent profiles must render Bone's port through {{ bone_port }}:\n  "
        + "\n  ".join(offenders)
    )


def test_the_scan_actually_covers_the_known_emitters():
    """A gate that scans nothing passes forever."""
    seen = set()
    for p in _files():
        if BONE_URL_ASSIGN.search(p.read_text(errors="replace")):
            # an agent is agents/<name>/agent.yml since 2026-08-28; name it by its dir
            seen.add(f"{p.parent.name}.yml" if p.name == "agent.yml" else p.name)
    for expected in ("conductor.yml", "drift-watch.sh", "gitleaks/plugin.yml".split("/")[-1]):
        assert expected in seen, (
            f"{expected} no longer matches the Bone-URL pattern — the scan may "
            f"have gone blind (path moved, or the variable was renamed)"
        )
