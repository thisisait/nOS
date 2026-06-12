"""Anatomy CI gate — devlog event types whitelisted on BOTH event sides.

The devlog write path POSTs through Bone (devlog_lib.emit_bone_event), so a
missing whitelist entry turns the audit write into a silent 400 — the exact
failure mode of the 2026-05-17 remediator incident. Wing's EventsPresenter
validates against EventRepository::VALID_TYPES (by-construction alignment),
so the two sources that must agree are Bone's events.py and the PHP constant.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone/events.py"
PHP_REPO = REPO / "files/anatomy/wing/app/Model/EventRepository.php"
PHP_PRESENTER = REPO / "files/anatomy/wing/app/Presenters/Api/EventsPresenter.php"

DEVLOG_TYPES = (
    "devlog_entry_created",
    "devlog_entry_updated",
    "devlog_entry_deleted",
    "devlog_sync_run",
    "devlog_published",
)


def test_bone_whitelists_devlog_types():
    src = BONE.read_text(encoding="utf-8")
    for t in DEVLOG_TYPES:
        assert f'"{t}"' in src, f"Bone VALID_TYPES missing {t}"


def test_wing_repository_whitelists_devlog_types():
    src = PHP_REPO.read_text(encoding="utf-8")
    for t in DEVLOG_TYPES:
        assert f"'{t}'" in src, f"Wing EventRepository VALID_TYPES missing {t}"


def test_presenter_validates_via_repository_constant():
    # The third surface stays aligned by construction — pin that it still
    # references the shared constant instead of growing its own list.
    src = PHP_PRESENTER.read_text(encoding="utf-8")
    assert re.search(r"EventRepository::VALID_TYPES", src), (
        "EventsPresenter no longer validates via EventRepository::VALID_TYPES — "
        "devlog types must be added to its own whitelist too"
    )


def test_emitters_use_whitelisted_types():
    lib = (REPO / "files/anatomy/scripts/devlog_lib.py").read_text(encoding="utf-8")
    sync = (REPO / "files/anatomy/scripts/devlog-sync.py").read_text(encoding="utf-8")
    post = (REPO / "tools/devlog-post.py").read_text(encoding="utf-8")
    assert '"devlog_sync_run"' in sync
    assert '"devlog_entry_updated"' in post and '"devlog_entry_created"' in post
    assert 'ACTOR_ID = "agent:devlog"' in lib
