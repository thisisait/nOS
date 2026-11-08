"""A file that leaves the commit path still runs somewhere (gate-diet, operator 2026-11-08).

tests/_lanes.yml moves toolchain and playbook harnesses off dev pushes. The joint is three
files: the list, the conftest hook that obeys it, and CI that runs it all at night and on PRs
to master, with `cargo test` in its own job. Any one of them drifting hides a gate for good.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))
import _lanes  # noqa: E402

CI = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8"))


def _collect(target: str, lane: str) -> list[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("NOS_PYTEST_SHARD", "NOS_LANE")}
    env["NOS_LANE"] = lane
    r = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--collect-only", "-q", target],
                       cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
    return [ln for ln in r.stdout.splitlines() if "::" in ln]


def test_every_listed_file_exists_and_says_why():
    listed = _lanes.listed()
    assert listed, "tests/_lanes.yml lists nothing"
    doc = yaml.safe_load(_lanes.LANES.read_text(encoding="utf-8"))
    gone = [p for p in listed if not (REPO / p).is_file()]
    bare = [p for lane in ("nightly", "cold") for p, why in (doc.get(lane) or {}).items() if not why]
    assert not gone, f"tests/_lanes.yml names files that do not exist: {gone}"
    assert not bare, f"a lane entry needs its reason (nightly) or date (cold): {bare}"


def test_a_listed_file_leaves_the_push_path_and_returns_with_all():
    target = next(p for p in _lanes.listed() if (REPO / p).is_file())
    folder = str(pathlib.Path(target).parent)
    push, every = _collect(folder, ""), _collect(folder, "all")
    assert not [n for n in push if n.startswith(target)], f"{target} still runs on a dev push"
    assert [n for n in every if n.startswith(target)], f"NOS_LANE=all does not bring {target} back"
    assert set(push) < set(every)


def test_ci_runs_every_lane_at_night_and_on_a_release_pr():
    lane = str(CI["jobs"]["pytest"]["env"].get("NOS_LANE", ""))
    for needed in ("schedule", "workflow_dispatch", "master", "'all'"):
        assert needed in lane, f"pytest job NOS_LANE must name {needed}: {lane!r}"


def test_cargo_runs_in_its_own_job():
    job = CI["jobs"].get("thalamus") or {}
    runs = " ".join(str(s.get("run", "")) for s in job.get("steps", []))
    assert "cargo test" in runs and "--workspace" in runs, "no CI job runs the thalamus workspace's cargo test"
    on = CI.get("on") or CI.get(True) or {}
    assert "push" in on and "pull_request" in on, "the cargo job must run on every push and PR"
    assert "if" not in job, "the cargo job must not be conditional"
