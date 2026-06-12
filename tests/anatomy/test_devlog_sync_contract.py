"""Anatomy CI gate — devlog sync engine + write-helper safety contract.

Pins:
  - the orphan delete in devlog-sync.py is TRIPLE-GUARDED: posts are listed
    filtered by bot author AND nos-core category, and only slugs absent from
    the bundle survive to deletion (the single most dangerous line of the
    devlog epic — a regression here deletes operator content);
  - a --dry-run/DRY_RUN path exists and gates every mutating call;
  - Bone HMAC bodies are canonical JSON (separators + sort_keys — the
    2026-05-17 canonical-JSON lesson) and emit failure never raises;
  - tools/devlog-post.py refuses --namespace nos-core with exit 2;
  - tasks/devlog-sync.yml is imported from main.yml behind install_wordpress
    + wordpress_devlog_enabled and skips gracefully without the credential.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SYNC = REPO / "files/anatomy/scripts/devlog-sync.py"
LIB = REPO / "files/anatomy/scripts/devlog_lib.py"
POST = REPO / "tools/devlog-post.py"
TASK = REPO / "tasks/devlog-sync.yml"
MAIN = REPO / "main.yml"


def test_orphan_delete_triple_guard():
    src = SYNC.read_text(encoding="utf-8")
    # Guard (a)+(b): the only post listing is filtered by author + category.
    assert "list_posts(author=" in src and "category=" in src
    # Guard (c): upserted slugs are POPPED from the map; only absentees remain.
    assert ".pop(entry[\"slug\"]" in src.replace("'", '"')
    lib = LIB.read_text(encoding="utf-8")
    assert '"author": author' in lib and '"categories": category' in lib, (
        "list_posts must filter server-side by author AND category"
    )


def test_dry_run_gates_every_mutation():
    src = SYNC.read_text(encoding="utf-8")
    assert 'env.get("DRY_RUN", "") == "1"' in src
    for mutation in ("wp.create_post", "wp.update_post", "wp.delete_post"):
        for m in re.finditer(re.escape(mutation), src):
            window = src[max(0, m.start() - 120): m.start()]
            assert "if not dry_run" in window, f"{mutation} not gated by dry_run"


def test_bone_emit_is_canonical_and_never_raises():
    lib = LIB.read_text(encoding="utf-8")
    assert 'separators=(",", ":"), sort_keys=True' in lib
    assert "return False" in lib.split("def emit_bone_event", 1)[1]


def test_post_helper_refuses_nos_core():
    proc = subprocess.run(
        [sys.executable, str(POST), "--namespace", "nos-core",
         "--title", "x", "--body-file", "/dev/null"],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 2, proc.stderr
    assert "repo-SoT" in proc.stderr


def test_playbook_wiring():
    main = MAIN.read_text(encoding="utf-8")
    assert "tasks/devlog-sync.yml" in main
    block = main.split("tasks/devlog-sync.yml", 1)[1][:400]
    assert "install_wordpress" in block and "wordpress_devlog_enabled" in block
    task = TASK.read_text(encoding="utf-8")
    assert "wordpress_devlog_app_password | default('') | length > 0" in task
