"""Anatomy CI gate — blank-reset post_blank plugin-hook ordering + tolerance.

tasks/blank-reset.yml fires the plugin loader's `post_blank` lifecycle hook so
plugins can do orderly cleanup of their OWN filesystem state (provisioning dirs,
cached downloads) BEFORE the data-dir wipe + Docker teardown. The task carries
`failed_when: false` — DOCUMENTED as intentional ("blank must continue even if
plugin cleanup misbehaves"; regulatory: audit-log rows in wing.db are NEVER
cleared by a blank). That tolerance was documented but UNGATED: nothing pinned
(1) the hook runs before Docker down, (2) the failure tolerance is present + on
purpose, or (3) the loader handles a plugin with no post_blank hooks gracefully
(forward-compat: returns status `ok`, note `no-op`).

This gate pins all four, so a refactor that:
  - moves the hook AFTER Docker down (plugins clean state Docker still holds),
  - drops `failed_when: false` (a misbehaving plugin manifest aborts the blank),
  - or regresses the loader's empty-hook handling
…is caught at lint time, not on a 3am unsupervised blank.

Sibling gates: test_blank_reset_tofu_state.py (tofu state reset ordering),
test_plugin_loader.py (library-level run_hook coverage).
"""

from __future__ import annotations

import pathlib

import yaml

# tests/conftest.py adds files/anatomy/ to sys.path.
from module_utils import load_plugins  # type: ignore  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BLANK_RESET_PATH = REPO_ROOT / "tasks" / "blank-reset.yml"

POST_BLANK_NAME_FRAGMENT = "Plugin loader"
DOCKER_DOWN_NAME_FRAGMENT = "Stop Docker stacks"
CONFIRM_NAME_FRAGMENT = "Confirm destructive operation"


def _load_tasks() -> list[dict]:
    data = yaml.safe_load(BLANK_RESET_PATH.read_text())
    assert isinstance(data, list), "blank-reset.yml must be a task list"
    return data


def _task_name(task: dict) -> str:
    return str(task.get("name", ""))


def _index_of(tasks: list[dict], fragment: str) -> int:
    for i, t in enumerate(tasks):
        if fragment in _task_name(t):
            return i
    return -1


def _post_blank_task(tasks: list[dict]) -> dict:
    for t in tasks:
        if POST_BLANK_NAME_FRAGMENT in _task_name(t) and "post_blank" in _task_name(t):
            return t
    raise AssertionError(
        "post_blank plugin-loader task vanished from blank-reset.yml — plugins "
        "would never get a chance to clean their own filesystem state before "
        "the data-dir wipe"
    )


# ── (1) the hook is wired with the post_blank lifecycle ────────────────────


def test_post_blank_hook_task_exists():
    """The plugin-loader post_blank task must be present and call the loader."""
    task = _post_blank_task(_load_tasks())
    assert "nos_plugin_loader" in task, (
        "post_blank task no longer invokes nos_plugin_loader — plugin cleanup lost"
    )
    loader = task["nos_plugin_loader"]
    assert loader.get("hook") == "post_blank", (
        "post_blank task no longer passes hook: post_blank — wrong lifecycle fired"
    )


# ── (2) the hook is called BEFORE Docker down ──────────────────────────────


def test_post_blank_hook_precedes_docker_down():
    """The post_blank hook must run BEFORE the Docker stacks are torn down.

    Plugins clean their own filesystem state (provisioning dirs, cached
    downloads) in post_blank; if Docker were already `down -v` it would have
    removed volumes the plugin may need to inspect, and the cleanup window
    would close. Sequence anchor: confirm prompt < post_blank < Docker down.
    """
    tasks = _load_tasks()
    confirm_idx = _index_of(tasks, CONFIRM_NAME_FRAGMENT)
    hook_idx = _index_of(tasks, POST_BLANK_NAME_FRAGMENT)
    docker_idx = _index_of(tasks, DOCKER_DOWN_NAME_FRAGMENT)

    assert hook_idx != -1, "post_blank hook task missing"
    assert docker_idx != -1, "Docker down anchor missing — file refactored"
    assert confirm_idx != -1, "confirm-prompt anchor missing — file refactored"

    assert confirm_idx < hook_idx < docker_idx, (
        "post_blank hook is out of sequence: it must run after the confirm "
        f"prompt (idx {confirm_idx}) and before Docker down (idx {docker_idx}), "
        f"but sits at idx {hook_idx} — plugins would clean state Docker already "
        "tore down"
    )


# ── (3) the failure tolerance is intentional, not a bug ────────────────────


def test_post_blank_hook_tolerates_failure_on_purpose():
    """`failed_when: false` must be present AND annotated as intentional.

    The plugin loader's post_blank hook re-raises on a misbehaving plugin
    manifest; the module wrapper then fail_json()s. `failed_when: false` is
    what keeps the blank going regardless — a regulatory requirement (audit-log
    rows in wing.db are never cleared by a blank, so a blank must always be able
    to complete). Drop it and one bad plugin aborts the whole reset.
    """
    task = _post_blank_task(_load_tasks())
    assert task.get("failed_when") is False, (
        "post_blank hook dropped `failed_when: false` — a misbehaving plugin "
        "manifest now aborts the entire blank (regression)"
    )

    # The intent must be documented inline so the tolerance reads as deliberate.
    raw = BLANK_RESET_PATH.read_text()
    assert "blank must continue even if plugin cleanup misbehaves" in raw, (
        "the `failed_when: false` intent comment was removed — the tolerance "
        "must stay documented as deliberate, not look like a forgotten guard"
    )
    # The reverse-topological + regulatory rationale lives in the section banner.
    assert "Reverse-topological order" in raw, (
        "the post_blank section banner lost its reverse-topo rationale"
    )


# ── (4) loader handles missing post_blank hooks gracefully (forward-compat) ─


def test_loader_post_blank_empty_plugin_set_returns_empty():
    """No plugins → post_blank hook is a clean no-op (empty result list)."""
    plugins: list = []
    results = load_plugins.run_hook("post_blank", plugins)
    assert results == [], (
        "post_blank with no plugins must return [] — empty-set must never raise"
    )


def test_loader_post_blank_plugin_without_hooks_returns_ok(tmp_path):
    """A plugin that declares NO post_blank lifecycle block must come back
    status=ok with a `no-op` note — never degraded/failed. This is the
    forward-compat contract: an older loader meeting a plugin that simply has
    no post_blank work to do must not trip the `failed_when: false` tolerance
    into hiding a real problem (there is none to hide)."""
    d = tmp_path / "noop-plugin"
    d.mkdir()
    (d / "plugin.yml").write_text(yaml.safe_dump({
        "name": "noop-plugin",
        "version": "0.1.0",
        "type": ["skill"],
        "gdpr": {
            "data_categories": ["test"],
            "data_subjects": ["operator"],
            "legal_basis": "legitimate_interests",
            "retention_days": 365,
            "processors": [],
        },
    }))
    plugins = load_plugins.discover(tmp_path)
    results = load_plugins.run_hook("post_blank", plugins)
    assert len(results) == 1
    assert results[0]["status"] == "ok", (
        "a plugin with no post_blank hooks must report ok, not degraded/failed"
    )
    assert results[0]["note"] == "no-op", (
        "a plugin with no post_blank actions must note `no-op` (forward-compat)"
    )
