"""End-to-end engine tests — orchestration, idempotency, rollback semantics."""

from __future__ import absolute_import, division, print_function

import os

import pytest

from module_utils.nos_migrate_engine import (
    apply,
    preview,
    validate_record,
    rollback_by_id,
    list_migrations,
    list_pending,
)


# ---------------------------------------------------------------------------
# Record builders

def _devboxnos_record(tmp_path):
    src = str(tmp_path / "src")
    dst = str(tmp_path / "dst")
    os.makedirs(src, exist_ok=True)
    return {
        "id": "2026-04-22-devboxnos-to-nos",
        "title": "Rename state dir",
        "summary": "test fixture",
        "severity": "breaking",
        "applies_if": {"fs_path_exists": src},
        "steps": [
            {
                "id": "move_state_dir",
                "detect": {"fs_path_exists": src},
                "action": {"type": "fs.mv", "src": src, "dst": dst},
                "verify": [{"fs_path_exists": dst}],
                "rollback": {"type": "fs.mv", "src": dst, "dst": src},
            },
        ],
        "post_verify": [{"type": "fs_path_exists", "path": dst}],
    }


def _multi_step_record(tmp_path):
    a = str(tmp_path / "a")
    b = str(tmp_path / "b")
    c_dir = str(tmp_path / "c")
    os.makedirs(a, exist_ok=True)
    return {
        "id": "multi-step",
        "title": "Multi-step fixture",
        "severity": "minor",
        "steps": [
            {
                "id": "step1_move",
                "detect": {"fs_path_exists": a},
                "action": {"type": "fs.mv", "src": a, "dst": b},
                "verify": [{"fs_path_exists": b}],
                "rollback": {"type": "fs.mv", "src": b, "dst": a},
            },
            {
                "id": "step2_ensure_dir",
                "detect": {"fs_path_exists": c_dir, "negate": True},
                "action": {"type": "fs.ensure_dir", "path": c_dir},
                "verify": [{"fs_path_exists": c_dir}],
                "rollback": {"type": "fs.rm", "path": c_dir},
            },
        ],
    }


# ---------------------------------------------------------------------------

def test_validate_record_rejects_missing_fields():
    with pytest.raises(ValueError):
        validate_record({"id": "x"})


def test_validate_record_rejects_bad_severity():
    with pytest.raises(ValueError):
        validate_record({
            "id": "x", "title": "t", "severity": "ehh", "steps": [
                {"id": "s", "action": {"type": "noop"}}
            ]})


def test_apply_happy_path(tmp_path, base_ctx):
    rec = _devboxnos_record(tmp_path)
    result = apply(rec, ctx=base_ctx)
    assert result["success"] is True
    assert result["steps_applied"] == 1
    assert (tmp_path / "dst").is_dir()
    # state got the migration record
    applied = base_ctx["state_client"].get("migrations_applied")
    assert applied and applied[-1]["id"] == rec["id"]


def test_apply_is_idempotent(tmp_path, base_ctx):
    rec = _devboxnos_record(tmp_path)
    r1 = apply(rec, ctx=base_ctx)
    assert r1["success"] is True
    # second apply: src gone, applies_if false → gated_out, steps_applied 0
    r2 = apply(rec, ctx=base_ctx)
    assert r2["success"] is True
    assert r2["steps_applied"] == 0


def test_preview_does_not_touch_fs(tmp_path, base_ctx):
    rec = _devboxnos_record(tmp_path)
    plan = preview(rec, ctx=base_ctx)
    assert plan["would_change"] is True
    assert (tmp_path / "src").exists()
    assert not (tmp_path / "dst").exists()


def test_precondition_abort(tmp_path, base_ctx):
    rec = _devboxnos_record(tmp_path)
    # inject unsatisfiable precondition
    rec["preconditions"] = [{"type": "no_active_coexistence"}]
    base_ctx["state_client"].set("coexistence.grafana", {"active_track": "new"})
    result = apply(rec, ctx=base_ctx)
    assert result["success"] is False
    assert result["phase"] == "precondition"
    # No fs side-effects.
    assert (tmp_path / "src").exists()
    assert not (tmp_path / "dst").exists()


def test_step_failure_triggers_rollback(tmp_path, base_ctx):
    # Build a record whose second step fails, so the first must be rolled back.
    a = str(tmp_path / "a")
    b = str(tmp_path / "b")
    os.makedirs(a, exist_ok=True)
    rec = {
        "id": "failing-step",
        "title": "Failing step",
        "severity": "minor",
        "steps": [
            {
                "id": "ok_step",
                "detect": {"fs_path_exists": a},
                "action": {"type": "fs.mv", "src": a, "dst": b},
                "verify": [{"fs_path_exists": b}],
                "rollback": {"type": "fs.mv", "src": b, "dst": a},
            },
            {
                "id": "bad_step",
                # action targets a non-existent path, and missing_ok=false → fails
                "action": {"type": "fs.rm",
                           "path": str(tmp_path / "nope"),
                           "missing_ok": False},
                "rollback": {"type": "noop", "reason": "nothing to undo"},
            },
        ],
    }
    result = apply(rec, ctx=base_ctx)
    assert result["success"] is False
    assert result["failed_step"] == "bad_step"
    # rollback of step1 should have moved b back to a.
    assert (tmp_path / "a").is_dir()
    assert not (tmp_path / "b").exists()


def test_verify_failure_triggers_rollback(tmp_path, base_ctx):
    a = str(tmp_path / "a")
    b = str(tmp_path / "b")
    os.makedirs(a, exist_ok=True)
    rec = {
        "id": "bad-verify",
        "title": "Verify fails",
        "severity": "minor",
        "steps": [{
            "id": "mv_step",
            "detect": {"fs_path_exists": a},
            "action": {"type": "fs.mv", "src": a, "dst": b},
            # verify references a path that will *never* exist → always false
            "verify": [{"fs_path_exists": str(tmp_path / "ghost")}],
            "rollback": {"type": "fs.mv", "src": b, "dst": a},
        }],
    }
    result = apply(rec, ctx=base_ctx)
    assert result["success"] is False
    assert result["phase"] == "verify"
    # rollback restored a
    assert os.path.isdir(a)
    assert not os.path.exists(b)


def test_detect_false_skips_step(tmp_path, base_ctx):
    """If a step's detect is false, it should be a no-op (not fail)."""
    a = str(tmp_path / "a")
    b = str(tmp_path / "b")
    rec = {
        "id": "skip-step",
        "title": "Skipped",
        "severity": "patch",
        "steps": [{
            "id": "mv",
            "detect": {"fs_path_exists": a},  # a doesn't exist
            "action": {"type": "fs.mv", "src": a, "dst": b},
            "rollback": {"type": "noop"},
        }],
    }
    result = apply(rec, ctx=base_ctx)
    assert result["success"] is True
    assert result["steps_applied"] == 0


def test_rollback_by_id(tmp_path, base_ctx):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    a = str(tmp_path / "a")
    b = str(tmp_path / "b")
    os.makedirs(b, exist_ok=True)  # simulate: forward was already applied
    # Write a YAML record
    import yaml
    rec = {
        "id": "rollback-test",
        "title": "RB test",
        "severity": "minor",
        "steps": [{
            "id": "mv",
            "action": {"type": "fs.mv", "src": a, "dst": b},
            "rollback": {"type": "fs.mv", "src": b, "dst": a},
        }],
    }
    with open(migrations_dir / "rollback-test.yml", "w") as fh:
        yaml.safe_dump(rec, fh)

    # seed state so rollback "removes" the applied entry
    base_ctx["state_client"].set("migrations_applied",
                                 [{"id": "rollback-test", "success": True}])
    result = rollback_by_id("rollback-test", base_ctx["state_client"].data,
                            str(migrations_dir), ctx=base_ctx)
    assert result["success"] is True
    assert result["steps_rolled_back"] >= 1
    assert os.path.isdir(a)
    assert not os.path.exists(b)
    # applied entry removed
    assert base_ctx["state_client"].get("migrations_applied") == []


def test_noop_rollback_recorded_as_non_reversible(tmp_path, base_ctx):
    """If a step's forward succeeds but rollback.type=noop, later rollback
    must mark it non-reversible, not error out."""
    a = str(tmp_path / "a")
    b = str(tmp_path / "b")
    os.makedirs(a, exist_ok=True)
    # Record with two steps: step1 succeeds, step2 fails, step1's rollback
    # is noop -> engine should tag it non-reversible, not error.
    rec = {
        "id": "noop-rollback",
        "title": "Non-reversible",
        "severity": "minor",
        "steps": [
            {
                "id": "step1",
                "detect": {"fs_path_exists": a},
                "action": {"type": "fs.mv", "src": a, "dst": b},
                "verify": [{"fs_path_exists": b}],
                "rollback": {"type": "noop", "reason": "unidirectional"},
            },
            {
                "id": "step2_bad",
                "action": {"type": "fs.rm",
                           "path": str(tmp_path / "nope"),
                           "missing_ok": False},
                "rollback": {"type": "noop"},
            },
        ],
    }
    result = apply(rec, ctx=base_ctx)
    assert result["success"] is False
    # step1 was applied-then-rolled-back-as-noop; data stays where it landed.
    assert os.path.isdir(b)
    assert not os.path.isdir(a)


def test_gate_false_no_ops_cleanly(tmp_path, base_ctx):
    rec = _devboxnos_record(tmp_path)
    # flip applies_if to false
    rec["applies_if"] = {"fs_path_exists": str(tmp_path / "absent")}
    result = apply(rec, ctx=base_ctx)
    assert result["success"] is True
    assert result["skipped"] == "applies_if_false"
    # src preserved
    assert (tmp_path / "src").exists()


def test_list_migrations_and_pending(tmp_path):
    import yaml
    md = tmp_path / "migrations"
    md.mkdir()
    rec_a = {"id": "2026-01-01-a", "title": "a", "severity": "patch",
             "steps": [{"id": "s", "action": {"type": "noop"}}]}
    rec_b = {"id": "2026-02-01-b", "title": "b", "severity": "minor",
             "steps": [{"id": "s", "action": {"type": "noop"}}]}
    with open(md / "2026-01-01-a.yml", "w") as fh:
        yaml.safe_dump(rec_a, fh)
    with open(md / "2026-02-01-b.yml", "w") as fh:
        yaml.safe_dump(rec_b, fh)
    # _template.yml must be skipped
    with open(md / "_template.yml", "w") as fh:
        yaml.safe_dump({"id": "_template"}, fh)

    all_mig = list_migrations(str(md))
    assert [i for (i, _p, _r) in all_mig] == ["2026-01-01-a", "2026-02-01-b"]

    pending = list_pending(str(md), {"migrations_applied": [
        {"id": "2026-01-01-a", "success": True}
    ]})
    assert [p["id"] for p in pending] == ["2026-02-01-b"]
