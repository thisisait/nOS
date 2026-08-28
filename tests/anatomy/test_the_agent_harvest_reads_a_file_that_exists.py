"""The agent-profile harvest must name a file agents actually have.

MEASURED 2026-08-28. `nos_plugin_loader` harvested `agents/<name>/profile.yml`
into the `agent_profile` aggregator that feeds `notification-routing.json`.
Nothing in this repo has ever been called profile.yml, so the harvest returned
an empty list on every converge, and every agent's `notification:` block —
four of them, each naming ntfy and mail for a CRITICAL — reached the sidecar
never. Bone then fell back to wing-inbox only, silently, which is exactly the
degradation `test_agent_notification_routing.py` was written to catch. It did
not catch it: that gate BUILDS a routing JSON the way the template would and
drives Bone's lookup over it, so it proves the routing shape and assumes the
harvest.

This runs the loader's own discovery against the real tree and requires it to
come back with the agents that declare routing.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
LOADER = REPO / "files/anatomy/library/nos_plugin_loader.py"
AGENTS = REPO / "files/anatomy/agents"


def _harvest_filename() -> str:
    """The basename the loader joins onto each agent directory."""
    m = re.search(r'ap_yml\s*=\s*ap_dir\s*/\s*"([^"]+)"', LOADER.read_text(encoding="utf-8"))
    assert m, "the agent-profile harvest no longer joins a filename — reread it"
    return m.group(1)


def test_the_harvest_filename_is_the_one_on_disk() -> None:
    name = _harvest_filename()
    dirs = [d for d in AGENTS.iterdir() if d.is_dir()]
    assert dirs, "no agent directories — this gate would pass vacuously"
    have = [d.name for d in dirs if (d / name).is_file()]
    assert have, (
        f"the loader harvests '{name}', which no agent directory contains "
        f"({[d.name for d in dirs]}). The harvest returns an empty list and "
        "every agent's notification routing is silently dropped."
    )


def test_every_agent_that_declares_routing_is_reachable() -> None:
    name = _harvest_filename()
    declaring = [
        d.name for d in sorted(AGENTS.iterdir())
        if (d / name).is_file()
        and (yaml.safe_load((d / name).read_text(encoding="utf-8")) or {}).get("notification")
    ]
    assert len(declaring) >= 4, (
        f"only {declaring} declare notification routing through the harvested "
        "file; the four scheduled ceremonies each route a CRITICAL to ntfy."
    )
