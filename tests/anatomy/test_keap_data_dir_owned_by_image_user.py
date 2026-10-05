"""On Linux the KEAP data dir must belong to the image's runtime user.

Measured: CI run 37265044993 (2026-10-05, first Linux run with install_keap)
crash-looped keap-1 for the whole health-wait. The image runs `USER node`
(uid 1000); the role created the /data bind source as the host user (runner,
uid 1001, 0755), so libsql died with `Unable to open connection to local
database /data/keap.db: 14` (SQLITE_CANTOPEN). Docker Desktop maps ownership,
which is why macOS never saw it. Reproduced with a nocopy volume owned 1001.

Pinned: the task that creates keap_data_dir sets owner keap_container_uid and
group = host gid (0775) off Darwin, with become; the default names uid 1000.
"""
from __future__ import annotations

import pathlib

import yaml

ROLE = pathlib.Path(__file__).resolve().parents[2] / "roles" / "pazny.keap"


def _data_dir_task() -> dict:
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))
    hits = [t for t in tasks if "keap_data_dir" in str(t.get("ansible.builtin.file", {}).get("path", ""))]
    assert len(hits) == 1, "expected one file task whose path is keap_data_dir"
    return hits[0]


def test_data_dir_is_owned_by_the_container_user_off_darwin() -> None:
    t = _data_dir_task()
    f = t["ansible.builtin.file"]
    owner, group = str(f.get("owner", "")), str(f.get("group", ""))
    assert "keap_container_uid" in owner and "Darwin" in owner, (
        "keap_data_dir owner must be keap_container_uid off Darwin — the image "
        "runs as uid 1000 and libsql cannot create keap.db otherwise"
    )
    assert "user_gid" in group and "0775" in str(f.get("mode", "")), (
        "the host user keeps write via group (post.yml touches .fixtures-seeded here)"
    )
    assert "Darwin" in str(t.get("become", "")), "chown to another uid needs become off Darwin"


def test_container_uid_default_is_the_image_user() -> None:
    d = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
    assert d.get("keap_container_uid") == 1000, "nos-keap Dockerfile: USER node (uid 1000)"
