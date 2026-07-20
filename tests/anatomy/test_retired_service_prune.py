"""Retired services get their compose overrides pruned before any bring-up.

2026-07-20: Puter was removed — role, plugin, Dockerfile and `files/puter/` all
deleted — but `~/stacks/iiab/overrides/{puter,puter-base}.yml` stayed on the live
host. The orchestrators discover overrides with `find`, so the dead fragments
were merged into `docker compose up` and the whole iiab stack failed to start:

    unable to prepare context: path ".../files/puter" not found

The render path is create-only; nothing reconciled the removal. These gates pin
the narrow reconciler that closes it.
"""

from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
PRUNE = ROOT / "tasks/stacks/prune-retired.yml"


def _config() -> dict:
    return yaml.safe_load((ROOT / "default.config.yml").read_text())


def test_prune_task_exists_and_is_wired_into_both_orchestrators():
    assert PRUNE.is_file(), "tasks/stacks/prune-retired.yml must exist"
    for orch in ("stack-up.yml", "core-up.yml"):
        src = (ROOT / "tasks/stacks" / orch).read_text()
        assert "prune-retired.yml" in src, (
            f"{orch} must prune retired overrides — a fragment left by a removed "
            "role is merged by the enumeration and fails the whole stack"
        )


def test_prune_runs_before_the_override_enumeration():
    """Order is the whole point: pruning after the `find` prunes nothing."""
    for orch, marker in (
        ("stack-up.yml", "Enumerate compose overrides per remaining stack"),
        ("core-up.yml", "Enumerate infra compose overrides"),
    ):
        src = (ROOT / "tasks/stacks" / orch).read_text()
        assert src.find("prune-retired.yml") < src.find(marker), (
            f"{orch}: the prune must precede the override enumeration"
        )


def test_retired_list_is_declared_with_a_real_default():
    """A `| default([])`-only var trips the eager-resolve trap on a live run."""
    cfg = _config()
    assert "nos_retired_services" in cfg, (
        "nos_retired_services must have a real definition in default.config.yml, "
        "not only a `| default([])` reference (the {{ vars }} eager-resolve trap)"
    )
    assert isinstance(cfg["nos_retired_services"], list)


def test_puter_is_recorded_as_retired():
    """The service whose leftovers proved the gap stays in the list."""
    assert "puter" in _config()["nos_retired_services"]


def test_retired_services_are_really_gone_from_the_repo():
    """A name here must have no role or plugin — otherwise the prune would
    delete the override of a service nOS still ships, every single run."""
    for svc in _config()["nos_retired_services"]:
        role = ROOT / f"roles/pazny.{svc}"
        plugin = ROOT / f"files/anatomy/plugins/{svc}-base"
        assert not role.exists(), f"{svc} is listed retired but {role} exists"
        assert not plugin.exists(), f"{svc} is listed retired but {plugin} exists"


def test_prune_covers_both_the_role_and_plugin_fragment():
    """A service renders TWO fragments: <svc>.yml (role) and <svc>-base.yml
    (plugin compose-extension). Missing the second leaves the stack broken."""
    src = PRUNE.read_text()
    assert "'.yml', '-base.yml'" in src or '".yml", "-base.yml"' in src, (
        "the prune must match both the role fragment and the plugin's -base one"
    )
