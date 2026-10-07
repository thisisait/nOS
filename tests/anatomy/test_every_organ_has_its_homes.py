"""Anatomy gate — an organ's id names its three homes (ssot/doctrine/body-plan.md §3).

WHY (repo-body-plan I-12, 2026-10-07). An organ is one row in state/manifest.yml;
the places that describe it are derived from its id, never remembered:
`roles/pazny.<id>/` renders it, `files/anatomy/plugins/<id>-base/` wires it,
`docs/systems/<id>/` explains it, with `_` → `-` in the plugin and docs names.
A home that is missing or spelt otherwise is a part a model cannot find from
the row. Today's seven organs without a full set are declared below with the
reason; the list may only shrink.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = REPO / "state" / "manifest.yml"

#: (row id, home) -> why that home is missing. 2026-10-07. Only ever delete lines.
EXCEPTIONS = {
    ("alloy", "role"): "tasks/observability.yml installs the brew service; no role of its own",
    ("tailscale", "role"): "tasks/tailscale.yml installs the cask; no role",
    ("tailscale", "plugin"): "no SSO, no notifications, no dashboard to wire",
    ("bone", "plugin"): "Bone is the bridge the plugins are wired through, not a wired service",
    ("opencode", "plugin"): "a CLI run on demand; nothing to wire",
    ("iiab_terminal", "plugin"): "an sshd ForceCommand TUI; nothing to wire",
    ("homeassistant", "docs"): "no docs/systems page yet",
    # I-12: dnsmasq became a row (it has a flag, a pin, a root daemon and an authored stop);
    # tasks/dnsmasq.yml is its whole implementation until a role is built.
    ("dnsmasq", "role"): "tasks/dnsmasq.yml installs and configures it; no role yet",
    ("dnsmasq", "plugin"): "local DNS for the edge; nothing to wire yet",
    ("dnsmasq", "docs"): "no docs/systems page yet",
}


def homes(rid: str) -> dict[str, pathlib.Path]:
    dashed = rid.replace("_", "-")
    return {"role": REPO / "roles" / f"pazny.{rid}",
            "plugin": REPO / "files" / "anatomy" / "plugins" / f"{dashed}-base",
            "docs": REPO / "docs" / "systems" / dashed}


def missing_homes(rows) -> list[tuple[str, str]]:
    return [(r["id"], home) for r in rows for home, p in homes(r["id"]).items() if not p.is_dir()]


def _rows():
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["services"]


def test_every_organ_has_its_three_homes_or_a_declared_reason():
    missing = set(missing_homes(_rows()))
    new = sorted(missing - set(EXCEPTIONS))
    assert not new, ("organs whose home is missing or not spelt from the id "
                     f"(roles/pazny.<id>, plugins/<id>-base, docs/systems/<id>, _ -> -): {new}")
    healed = sorted(set(EXCEPTIONS) - missing)
    assert not healed, f"homes that exist now — delete them from EXCEPTIONS: {healed}"


def test_the_reader_goes_red_on_a_planted_organ():
    assert missing_homes([{"id": "zzz_planted"}]) == [
        ("zzz_planted", "role"), ("zzz_planted", "plugin"), ("zzz_planted", "docs")]
    assert missing_homes([{"id": "grafana"}]) == []
