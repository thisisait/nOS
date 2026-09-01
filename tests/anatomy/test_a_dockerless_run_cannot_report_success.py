"""Anatomy CI gate — a run asked for stacks must refuse to finish without Docker.

MEASURED 2026-09-01: 18 tasks gate on `nos_docker_ready` and nothing asserted
it, so a fresh-Mac converge where Docker never came up ends `failed=0` with no
service installed — and ansible.cfg's display_skipped_hosts=false prints no
banner for the skips, so the log looks clean.

Pinned: main.yml refuses; the refusal carries core-up's OWN tags (so
`--tags dotfiles` is unaffected); and the escape defaults FALSE, declared
per-invocation in ci.yml rather than in default.config.yml. An escape that
ships on by default is the old behaviour with a longer name.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MAIN = REPO / "main.yml"
CI = REPO / ".github" / "workflows" / "ci.yml"
CONFIG = REPO / "default.config.yml"
FLAG = "nos_allow_no_docker"


def _stack_tasks() -> list[dict]:
    plays = yaml.safe_load(MAIN.read_text(encoding="utf-8"))
    out = []
    for play in plays:
        for key in ("pre_tasks", "tasks", "post_tasks"):
            out.extend(play.get(key) or [])
    return out


def _refusal() -> dict | None:
    for t in _stack_tasks():
        if "fail" not in " ".join(t.keys()):
            continue
        if "nos_docker_ready" in str(t.get("when", "")):
            return t
    return None


def test_the_playbook_refuses_a_dockerless_stack_run():
    t = _refusal()
    assert t is not None, (
        "main.yml no longer fails when nos_docker_ready is false. 18 tasks are "
        "gated on that fact; without a refusal a converge that installed "
        "nothing reports failed=0, and display_skipped_hosts=false hides the "
        "skips that would have shown it")


def test_the_refusal_is_scoped_to_runs_that_wanted_docker():
    """Blanket-failing every tag selection would make `--tags dotfiles` unusable
    on a Docker-less host. It carries core-up's tags instead, so tag filtering
    decides — the same mechanism that selects the work it is protecting."""
    t = _refusal()
    tags = set(t.get("tags") or [])
    core_up = next(
        (x for x in _stack_tasks()
         if "core-up.yml" in str(x.get("import_tasks", ""))), None)
    assert core_up is not None, "main.yml no longer imports core-up.yml"
    assert tags == set(core_up.get("tags") or []), (
        f"the refusal's tags {sorted(tags)} do not match core-up's "
        f"{sorted(core_up.get('tags') or [])}. They must be identical or the "
        "refusal fires on runs that never wanted Docker, or misses runs that "
        "did")
    assert "always" not in tags, (
        "the refusal is tagged `always`, so it fires on every run including "
        "host-only ones. Tag filtering is what makes it precise")


def test_the_escape_defaults_to_off_and_is_not_a_config_default():
    t = _refusal()
    when = str(t.get("when", ""))
    assert FLAG in when, (
        f"the refusal has no {FLAG} escape; the CI host-only lane cannot "
        "declare its exception and would go permanently red")
    assert re.search(rf"{FLAG}\s*\|\s*default\(false\)", when), (
        f"{FLAG} must default to FALSE in the condition — an escape that "
        "defaults true is the unguarded behaviour wearing a longer name")
    assert not re.search(rf"^{FLAG}\s*:", CONFIG.read_text(encoding="utf-8"), re.M), (
        f"{FLAG} is declared in default.config.yml. It must be passed "
        "per-invocation so the exception is visible in the file that takes it, "
        "not inherited silently by every operator")


def test_only_the_dockerless_ci_lane_claims_the_escape():
    """The Linux lane HAS Docker and is the intended gating wet-test. If it
    ever carries the escape, the one job that proves the stacks stops proving
    them and says nothing."""
    ci = CI.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in ci.splitlines()
             if FLAG in ln and not ln.lstrip().startswith("#")]
    assert lines, (
        f"no CI invocation declares {FLAG}; the macOS host-only lane has no "
        "Docker and would now fail")
    for ln in lines:
        assert "main.yml" in ln, (
            f"{FLAG} appears somewhere other than a playbook invocation, where "
            f"its scope is not obvious:\n  {ln}")
    # The Linux integration job's invocation is a block scalar naming install_traefik.
    linux = re.search(r"install_traefik.*?\n(?:.*\n){0,6}", ci)
    assert linux and FLAG not in linux.group(0), (
        "the Linux integration lane carries the no-Docker escape. That job is "
        "the one wet-test that must prove the compose layer; with the escape it "
        "would pass an empty estate the way hidden fee 08 describes")


def test_the_other_half_of_the_cover_survives():
    """The refusal above only fires when `nos_docker_ready` was actually SET,
    i.e. when the tag selection reached tasks/iiab/docker-prereqs.yml
    (['iiab','docker','stacks']). Under `--tags core` the fact is unset,
    `default(true)` wins and this skips — correctly, since a run that never
    probed must not fail on a guess.

    What catches the dead daemon in THAT path is core-up's own daemon wait,
    which retries and fails hard. Measured 2026-09-01 with a `docker` stub
    exiting 1: `--tags core` fails at that wait, `--tags docker,core` fails at
    the refusal. Neither alone covers both selections, so this pins the half
    that is easy to soften into a warning.
    """
    core_up = (REPO / "tasks" / "stacks" / "core-up.yml").read_text(encoding="utf-8")
    tasks = yaml.safe_load(core_up)
    wait = next(
        (t for t in tasks
         if "Wait for Docker daemon" in str(t.get("name", ""))), None)
    assert wait is not None, (
        "core-up.yml lost its Docker daemon wait. With `--tags core` the "
        "refusal in main.yml cannot fire (the fact is never set), so this is "
        "the only thing standing between a dead daemon and a silent run")
    assert wait.get("failed_when") is not False, (
        "core-up's daemon wait is now `failed_when: false`. It was the hard "
        "failure covering the tag selections the main.yml refusal cannot see")
    assert wait.get("ignore_errors") is not True, (
        "core-up's daemon wait ignores errors; same defect as above")
