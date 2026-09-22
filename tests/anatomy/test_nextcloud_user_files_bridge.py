"""Class-3 bridge: the per-user doctrine tree reaches Nextcloud (and through
its connector, euro-office/OnlyOffice) as a per-user external storage.

Before 2026-09-21 the face Files app / Bone VFS tree (class 3,
tenants/<slug>/users/) and Nextcloud's data (class 2, shared/nextcloud/data)
were disjoint: a document created in Files was invisible to Nextcloud and so
uneditable by the document server, and an edited document never reached the
user's inbox/ or KEAP's per-user fs-sync. The bridge is one bind mount + one
`files_external:create` with NC's `$user` placeholder.

What this gate refuses:
- a mount re-pointed outside nos_data_root/tenants/<slug>/users (ssot/doctrine/filesystem.md §6:
  "a volume mount SHALL NOT sit outside nos_data_root");
- the mount without the occ half or the occ half without the mount;
- a success claimed by the attempting task (the read-back list is the verdict).
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = REPO / "roles/pazny.nextcloud/templates/compose.yml.j2"
POST = REPO / "roles/pazny.nextcloud/tasks/post.yml"


def test_compose_binds_the_user_tree_inside_the_doctrine_root():
    src = COMPOSE.read_text(encoding="utf-8")
    line = next((l for l in src.splitlines() if ":/nos-user-files" in l), None)
    assert line, "the /nos-user-files bind is gone — the occ mount points at a void"
    host = line.strip().lstrip("-").strip().split(":/nos-user-files")[0].strip()
    assert host == "{{ nos_data_root }}/tenants/{{ nos_tenant_slug }}/users", (
        f"bridge host path {host!r} must derive from nos_data_root and land "
        "under tenants/<slug>/users — nothing outside the doctrine tree"
    )


def test_post_registers_the_per_user_mount_and_reads_it_back():
    src = POST.read_text(encoding="utf-8")
    assert "files_external:create" in src, "occ half of the bridge is gone"
    assert "datadir=/nos-user-files/$user" in src, (
        "the $user placeholder is the whole design — one definition, every "
        "user, no per-user loop"
    )
    assert "app:enable" in src and "files_external" in src
    # no silent green: the verify task FAILS unless the read-back listing
    # carries the mount (the create task's own rc proves nothing durable).
    # The predicate matches 'nos-user-files' and '$user' as separate tokens —
    # occ --output=json escapes slashes, so the literal path is never in the
    # JSON (the first live run failed its own read-back on exactly that).
    verify = src.index("Read back: the mount is registered")
    tail = src[verify:].split("failed_when:")[1][:300]
    assert "nos-user-files" in tail and "$user" in tail
    assert "'/nos-user-files/$user' not in" not in src, (
        "literal-path predicate — always true against escaped JSON: the create "
        "duplicates the mount every converge and the verify always fails"
    )


def test_bridge_is_guarded_like_every_other_nc_post_step():
    src = POST.read_text(encoding="utf-8")
    block = src[src.index("Class-3 bridge"):]
    assert block.count("_nc_container.stdout") >= 4, (
        "every bridge task must skip cleanly when the NC container is absent"
    )
    assert "__NC_NOT_INSTALLED__" in block
