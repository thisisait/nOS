"""Test files the commit path skips: tests/_lanes.yml names them (gate-diet, operator 2026-11-08).

Unset NOS_LANE (a dev push, tests/fast.sh) deselects every listed file unless the file was
named on the command line; NOS_LANE=all (nightly CI, PRs to master) runs everything.
Pinned by tests/anatomy/test_lanes_hold.py.
"""
from __future__ import annotations

import os
import pathlib

import yaml

LANES = pathlib.Path(__file__).with_name("_lanes.yml")


def listed() -> dict[str, str]:
    """path -> lane, for every file a lane names."""
    doc = yaml.safe_load(LANES.read_text(encoding="utf-8")) or {}
    out: dict[str, str] = {}
    for lane in ("nightly", "cold"):
        for path in doc.get(lane) or {}:
            out[path] = lane
    return out


def deselect(config, items) -> None:
    if os.environ.get("NOS_LANE", "").strip() == "all":
        return
    here = config.invocation_params.dir
    named = {str((here / a.split("::")[0]).resolve()) for a in config.args}
    skip = {p for p in listed() if str((config.rootpath / p).resolve()) not in named}
    if not skip:
        return
    drop = [i for i in items if i.nodeid.split("::")[0] in skip]
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = [i for i in items if i.nodeid.split("::")[0] not in skip]
