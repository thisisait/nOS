"""backup.volume and backup.restore — idempotence + uniqueness."""

from __future__ import absolute_import, division, print_function

import os
import os.path
import tarfile

from module_utils.nos_upgrade_actions import backup as bk


def _mkdata(tmp_path, name="data"):
    d = tmp_path / name
    d.mkdir()
    (d / "hello.txt").write_text("hello")
    sub = d / "sub"
    sub.mkdir()
    (sub / "inner.bin").write_bytes(b"\x00\x01\x02")
    return str(d)


def test_backup_volume_creates_tarball(tmp_path, base_ctx):
    src = _mkdata(tmp_path)
    res = bk.handle_backup_volume(
        {"src": src, "label": "pre-test-1"},
        base_ctx,
    )
    assert res["success"]
    assert res["changed"]
    tgz = os.path.join(base_ctx["backup_root"], "pre-test-1.tar.gz")
    assert os.path.isfile(tgz)
    meta = os.path.join(base_ctx["backup_root"], "pre-test-1.meta.json")
    assert os.path.isfile(meta)
    with tarfile.open(tgz, "r:gz") as tf:
        names = tf.getnames()
    assert any(n.endswith("hello.txt") for n in names)


def test_backup_volume_is_idempotent_for_same_label(tmp_path, base_ctx):
    src = _mkdata(tmp_path)
    r1 = bk.handle_backup_volume({"src": src, "label": "same"}, base_ctx)
    r2 = bk.handle_backup_volume({"src": src, "label": "same"}, base_ctx)
    assert r1["success"] and r1["changed"]
    assert r2["success"] and not r2["changed"]
    assert r2["result"]["reason"] == "backup_exists"


def test_backup_label_uniqueness_via_timestamp_suffix(tmp_path, base_ctx):
    """Engine supplies timestamp suffix; two distinct labels must coexist."""
    src = _mkdata(tmp_path)
    bk.handle_backup_volume({"src": src, "label": "pre-up-20260422T120000Z"}, base_ctx)
    bk.handle_backup_volume({"src": src, "label": "pre-up-20260422T120105Z"}, base_ctx)
    entries = sorted(os.listdir(base_ctx["backup_root"]))
    tarballs = [e for e in entries if e.endswith(".tar.gz")]
    assert len(tarballs) == 2


def test_backup_volume_missing_src_fails(tmp_path, base_ctx):
    res = bk.handle_backup_volume({"src": str(tmp_path / "nope"), "label": "x"}, base_ctx)
    assert not res["success"]


def test_backup_restore_roundtrip(tmp_path, base_ctx):
    src = _mkdata(tmp_path, name="data")
    bk.handle_backup_volume({"src": src, "label": "rt"}, base_ctx)

    # Corrupt data.
    (tmp_path / "data" / "hello.txt").write_text("CORRUPTED")
    (tmp_path / "data" / "extra").write_text("junk")

    res = bk.handle_backup_restore({"dst": src, "label": "rt"}, base_ctx)
    assert res["success"]
    assert res["changed"]

    # Post-restore state matches pre-backup state.
    assert (tmp_path / "data" / "hello.txt").read_text() == "hello"
    assert (tmp_path / "data" / "sub" / "inner.bin").read_bytes() == b"\x00\x01\x02"
    # Junk added post-backup should be gone (restore wipes dst first).
    assert not (tmp_path / "data" / "extra").exists()


def test_backup_restore_missing_archive_strict(tmp_path, base_ctx):
    src = _mkdata(tmp_path)
    res = bk.handle_backup_restore({"dst": src, "label": "missing"}, base_ctx)
    assert not res["success"]


def test_backup_restore_missing_archive_lenient(tmp_path, base_ctx):
    src = _mkdata(tmp_path)
    res = bk.handle_backup_restore(
        {"dst": src, "label": "missing", "strict": False},
        base_ctx,
    )
    assert res["success"]
    assert not res["changed"]


def test_backup_dry_run_makes_no_files(tmp_path, base_ctx):
    base_ctx["dry_run"] = True
    src = _mkdata(tmp_path)
    res = bk.handle_backup_volume({"src": src, "label": "dry"}, base_ctx)
    assert res["success"]
    assert res["changed"]  # "would create"
    assert not os.path.exists(base_ctx["backup_root"])
