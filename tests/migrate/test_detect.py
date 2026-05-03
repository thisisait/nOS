"""Predicate evaluator tests."""

from __future__ import absolute_import, division, print_function

import os

import pytest

from module_utils.nos_migrate_detect import evaluate, PredicateError


def test_fs_path_exists_shorthand(tmp_path, base_ctx):
    p = tmp_path / "exists"
    p.write_text("x")
    assert evaluate({"fs_path_exists": str(p)}, base_ctx) is True
    assert evaluate({"fs_path_exists": str(tmp_path / "nope")}, base_ctx) is False


def test_fs_path_exists_with_negate(tmp_path, base_ctx):
    p = tmp_path / "exists"
    p.write_text("x")
    assert evaluate({"fs_path_exists": str(p), "negate": True}, base_ctx) is False


def test_fs_path_exists_type_form(tmp_path, base_ctx):
    p = tmp_path / "exists"
    p.write_text("x")
    assert evaluate({"type": "fs_path_exists", "path": str(p)}, base_ctx) is True


def test_launchagent_matches(tmp_path, base_ctx):
    d = tmp_path / "LaunchAgents"
    d.mkdir()
    (d / "com.devboxnos.a.plist").write_text("")
    base_ctx["launchagents_dir"] = str(d)
    assert evaluate({"launchagent_matches": "com.devboxnos.*"}, base_ctx) is True
    assert evaluate({"launchagent_matches": "com.other.*"}, base_ctx) is False


def test_launchagents_matching_with_count(tmp_path, base_ctx):
    d = tmp_path / "LaunchAgents"
    d.mkdir()
    (d / "com.devboxnos.a.plist").write_text("")
    base_ctx["launchagents_dir"] = str(d)
    assert evaluate({"launchagents_matching": "com.devboxnos.*",
                     "count": 0}, base_ctx) is False
    # remove and recheck
    (d / "com.devboxnos.a.plist").unlink()
    assert evaluate({"launchagents_matching": "com.devboxnos.*",
                     "count": 0}, base_ctx) is True


def test_authentik_group_exists(base_ctx):
    base_ctx["authentik_client"].groups["nos-admins"] = {"members": []}
    assert evaluate({"authentik_group_exists": "nos-admins"}, base_ctx) is True
    assert evaluate({"authentik_group_exists": "nos-unicorns"}, base_ctx) is False


def test_state_schema_version_lt(base_ctx):
    base_ctx["state_client"].set("schema_version", 1)
    assert evaluate({"state_schema_version_lt": 2}, base_ctx) is True
    assert evaluate({"state_schema_version_lt": 1}, base_ctx) is False


def test_all_of_any_of_not(tmp_path, base_ctx):
    p = tmp_path / "here"
    p.write_text("")
    # all_of with one true, one false → false
    assert evaluate({"all_of": [
        {"fs_path_exists": str(p)},
        {"fs_path_exists": str(tmp_path / "ghost")},
    ]}, base_ctx) is False
    assert evaluate({"any_of": [
        {"fs_path_exists": str(p)},
        {"fs_path_exists": str(tmp_path / "ghost")},
    ]}, base_ctx) is True
    assert evaluate({"not": {"fs_path_exists": str(tmp_path / "ghost")}}, base_ctx) is True


def test_compose_image_tag_is(tmp_path, base_ctx):
    overrides = tmp_path / "stacks" / "observability" / "overrides"
    overrides.mkdir(parents=True)
    (overrides / "grafana.yml").write_text(
        "services:\n"
        "  grafana:\n"
        "    image: grafana/grafana-oss:11.5.0\n"
    )
    assert evaluate({"compose_image_tag_is": {
        "service": "grafana", "tag": "11.5.0",
        "overrides_dir": str(overrides),
    }}, base_ctx) is True
    assert evaluate({"compose_image_tag_is": {
        "service": "grafana", "tag": "12.0.0",
        "overrides_dir": str(overrides),
    }}, base_ctx) is False


def test_unknown_predicate_raises(base_ctx):
    with pytest.raises(PredicateError):
        evaluate({"wat": True}, base_ctx)


def test_combinators_type_form(tmp_path, base_ctx):
    """Post_verify commonly spells combinators with explicit type: ... + of: ...
    `type: negate` (and `type: not`) invert an inner predicate."""
    p = tmp_path / "here"
    p.write_text("")
    ghost = str(tmp_path / "ghost")

    # type: negate
    assert evaluate({"type": "negate",
                     "of": {"type": "fs_path_exists", "path": ghost}},
                    base_ctx) is True
    assert evaluate({"type": "negate",
                     "of": {"type": "fs_path_exists", "path": str(p)}},
                    base_ctx) is False

    # type: not (alias)
    assert evaluate({"type": "not",
                     "of": {"fs_path_exists": ghost}}, base_ctx) is True

    # type: all_of / any_of with of: [...]
    assert evaluate({"type": "all_of",
                     "of": [{"fs_path_exists": str(p)},
                            {"fs_path_exists": ghost}]}, base_ctx) is False
    assert evaluate({"type": "any_of",
                     "of": [{"fs_path_exists": str(p)},
                            {"fs_path_exists": ghost}]}, base_ctx) is True


def test_negate_missing_of_raises(base_ctx):
    with pytest.raises(PredicateError):
        evaluate({"type": "negate"}, base_ctx)


# ---------------------------------------------------------------------------
# Catalog smoke test — every migration in migrations/*.yml must declare
# applies_if / preconditions / steps.*.detect|verify / post_verify predicates
# that the evaluator recognises.  Catches predicate-form bugs at CI time
# instead of on the host during blank-run.

import glob as _glob  # noqa: E402
import os.path as _osp  # noqa: E402


def _collect_predicates(rec):
    """Yield every predicate the engine will evaluate for a migration record."""
    if rec.get("applies_if") is not None:
        yield ("applies_if", rec["applies_if"])
    for pre in rec.get("preconditions") or []:
        yield ("preconditions", pre)
    for step in rec.get("steps") or []:
        sid = step.get("id", "?")
        if step.get("detect") is not None:
            yield ("steps.%s.detect" % sid, step["detect"])
        for v in step.get("verify") or []:
            yield ("steps.%s.verify" % sid, v)
    for pv in rec.get("post_verify") or []:
        yield ("post_verify", pv)


def _migration_files():
    root = _osp.abspath(_osp.join(_osp.dirname(__file__), "..", ".."))
    # Anatomy A1 (2026-05-03): migrations moved from /migrations/ to
    # files/anatomy/migrations/ per refactor §4.2.
    mdir = _osp.join(root, "files", "anatomy", "migrations")
    return sorted(f for f in _glob.glob(_osp.join(mdir, "*.yml"))
                  if not _osp.basename(f).startswith("_"))


@pytest.mark.parametrize("migration_path", _migration_files())
def test_catalog_predicates_parseable(migration_path, tmp_path):
    """Every predicate in every shipped migration must be parseable through
    the same code path the engine uses (``_check_precondition`` for
    preconditions, ``evaluate`` for everything else).

    Evaluation result is not asserted — only that the shape parses without
    structural errors.  Predicates that touch external state (Authentik,
    compose files) may raise under a stub ctx; that's allowed.  The bug
    class we want to catch is "predicate must contain exactly one type key"
    and siblings — pure structural errors the engine should never emit at
    runtime.
    """
    import yaml as _yaml
    from module_utils.nos_migrate_engine import _check_precondition

    with open(migration_path) as fh:
        rec = _yaml.safe_load(fh) or {}
    ctx = {"launchagents_dir": str(tmp_path),
           "expand_path": lambda p: p,
           "state_client": None,
           "authentik_client": None}

    def _structural(msg):
        return (
            "predicate must contain exactly one type key" in msg
            or "predicate must be dict/list/bool" in msg
            or "requires 'of'" in msg
            or "precondition must be a mapping" in msg
            or "precondition missing 'type'" in msg
        )

    for location, pred in _collect_predicates(rec):
        if location == "preconditions":
            ok, detail = _check_precondition(pred, ctx)
            err = (detail or {}).get("error", "") if not ok else ""
            assert not _structural(err), (
                "preconditions in %s unparseable: %s\npredicate=%r" %
                (_osp.basename(migration_path), err, pred)
            )
            continue
        try:
            evaluate(pred, ctx)
        except PredicateError as exc:
            assert not _structural(str(exc)), (
                "%s in %s unparseable: %s\npredicate=%r" %
                (location, _osp.basename(migration_path), exc, pred)
            )
