"""Authentik's resource knobs live in the default config layer, so a profile can size them.

2026-10-14, the core profile on a client: Authentik is half the core's memory, and its workers,
threads and limits sat in roles/pazny.authentik/defaults — which a profile may not set
(test_a_profile_only_sets_flags_that_exist.py). A hard limit is a config knob, not a role default.
"""

from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
KNOBS = ("authentik_mem_limit", "authentik_worker_mem_limit", "authentik_cpus", "authentik_web_workers",
         "authentik_web_threads", "authentik_worker_processes", "authentik_worker_threads")


def test_the_knobs_are_declared_once_in_the_default_layers():
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity
    layered = nos_identity.default_config()
    role = yaml.safe_load((REPO / "roles/pazny.authentik/defaults/main.yml").read_text()) or {}
    for k in KNOBS:
        assert k in layered, f"{k} is not a config knob"
        assert k not in role, f"{k} is also a role default: declared twice"


def test_the_core_profile_trims_authentik_threads():
    core = yaml.safe_load((REPO / "profiles/core.yml").read_text())
    assert core["authentik_web_threads"] == 2 and core["authentik_worker_threads"] == 1, core
    assert core["authentik_web_workers"] >= 2, "gunicorn refuses fewer than 2 web workers"
