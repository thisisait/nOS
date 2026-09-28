"""Every `*_dir` var in default.config.yml is either in backup_dirs_to_dump or
declared in `backup_coverage` with a class and a reason.

Measured 2026-09-28 with the same resolver the blank gate uses: 62 of 72 dir
vars sat outside the backup set and nothing said whether that was a dump
elsewhere, derived state, or a real hole. Twenty of them are real holes
(Stalwart mailboxes, Kuma's monitors, Open WebUI chats, every attachment
store). The list does not close them; it makes adding a service without a
backup verdict a red gate instead of a silence. `unbacked` is the honest gap
list — `tools/backup-coverage.py` prints it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("blank_gate", REPO / "tests/anatomy/test_blank_reset_data_dirs.py")
blank_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(blank_gate)

CLASSES = {"dump", "db", "derived", "store", "never", "unbacked"}


def _state():
    env = blank_gate._jinja()
    ctx = blank_gate._config_ctx(env)
    dirs = blank_gate._dir_vars(ctx)
    cfg = yaml.safe_load((REPO / "default.config.yml").read_text())
    backed = {env.from_string(d["path"]).render(ctx).rstrip("/") for d in cfg["backup_dirs_to_dump"]}
    return dirs, backed, cfg["backup_coverage"]


def test_every_dir_var_is_backed_up_or_declared():
    dirs, backed, cov = _state()
    assert len(dirs) > 40
    undeclared = sorted(k for k, v in dirs.items() if not blank_gate._covered(v, backed) and k not in cov)
    assert not undeclared, (
        "these default.config.yml dirs are outside backup_dirs_to_dump and "
        "backup_coverage says nothing about them:\n  " + "\n  ".join(undeclared))


def test_every_declaration_is_well_formed_and_current():
    dirs, backed, cov = _state()
    bad = {k: e for k, e in cov.items() if e.get("class") not in CLASSES or not e.get("why")}
    assert not bad, f"class must be one of {sorted(CLASSES)} and why non-empty: {sorted(bad)}"
    stale = sorted(k for k in cov if k in dirs and blank_gate._covered(dirs[k], backed))
    assert not stale, f"declared but backup_dirs_to_dump covers them — drop: {stale}"
    unknown = sorted(k for k in cov if k not in dirs)
    assert not unknown, f"backup_coverage names dirs default.config.yml does not define: {unknown}"


def test_the_gap_list_is_readable():
    """A reader prints the unbacked set; a class nobody can list is prose."""
    dirs, backed, cov = _state()
    gap = sorted(k for k, e in cov.items() if e["class"] == "unbacked")
    assert gap, "no unbacked dirs declared — either the estate is fully covered (prove it) or the class was dropped"
    for k in gap:
        assert k in dirs
