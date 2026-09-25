"""nos_plugin_loader reports `changed` only when an action changed the host.

Before 2026-09-25 any hook note other than the literal "no-op" counted as a
change, so `render_dir: 0 rendered / 7 unchanged` and a bare `wait_health`
made the pre/post_compose hooks `changed` on every converge — two of the
twelve tasks the cloud e2e idempotence tier found (docs/cloud-e2e.md).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files" / "anatomy"))
from module_utils import load_plugins  # noqa: E402

UNCHANGED = [
    "no-op",
    "ensure_dir:/x/y:exists",
    "render_dir:blueprints:0 rendered / 7 unchanged -> /x",
    "render:compose:unchanged -> /x/y.yml",
    "render_compose_extension:ext:unchanged -> /x/y.yml",
    "copy_dir:alerts:0 copied / 3 unchanged -> /x",
    "copy_dashboards:d:0/4 updated -> /x",
    "wait_health:http://127.0.0.1:8082/ping:ok",
    "remove_file:/x/y:absent",
    "conditional_remove_dir:/x:preserved(when=False)",
    "replay_api_calls:seq:skipped(no sequence found)",
    "replay_api_calls:0 executed / 2 skipped",
    "ensure_dir:/a:exists, render_dir:b:0 rendered / 7 unchanged -> /c",
]
CHANGED = [
    "ensure_dir:/x/y:created",
    "render_dir:blueprints:1 rendered / 6 unchanged -> /x",
    "render:compose:changed -> /x/y.yml",
    "copy_dir:alerts:2 copied / 1 unchanged -> /x",
    "copy_dashboards:d:1/4 updated -> /x",
    "remove_dir:/x:removed",
    "conditional_remove_dir:/x:removed",
    "replay_api_calls:3 executed / 0 skipped",
    "some_future_action:did-something",          # unknown shape -> change
    "ensure_dir:/a:exists, render:c:changed -> /d",
]


@pytest.mark.parametrize("note", UNCHANGED)
def test_steady_notes_are_not_changes(note):
    assert load_plugins.note_changed(note) is False


@pytest.mark.parametrize("note", CHANGED)
def test_writes_are_changes(note):
    assert load_plugins.note_changed(note) is True


def test_the_module_uses_it():
    mod = (REPO / "files/anatomy/library/nos_plugin_loader.py").read_text()
    assert "load_plugins.note_changed(" in mod
    assert 'r["note"] != "no-op"' not in mod


def test_render_collapses_trailing_newlines_like_ansible(tmp_path):
    """The loader and the role both write 00-admin-groups/30-agent-clients.
    A template ending in `{% endfor %}\\n` must not gain a blank last line
    here that Ansible's template does not write."""
    src = tmp_path / "t.j2"
    src.write_text("a:\n{% for x in [1] %}\n  - {{ x }}\n{% endfor %}\n")
    dest = tmp_path / "out.yaml"
    load_plugins._render_file(src, dest, {})
    assert dest.read_text().endswith("- 1\n") and not dest.read_text().endswith("\n\n")
    assert load_plugins._render_file(src, dest, {}) is False   # steady
