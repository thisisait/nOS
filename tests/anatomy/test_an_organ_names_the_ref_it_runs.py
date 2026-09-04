"""`repo != running system`, asked of the organs themselves.

The doctrine this repo is named for was unanswerable of its own two primary
organs: Bone and Wing answered /health and omitted what they were running, so
estate-status printed a permanent `?` (UNREADABLE) for both (roadmap
organ-health-carries-a-version; measured live 2026-09-03/04).

The fix: the converge stamps the git ref it deploys FROM into each organ (Bone
reads a file in its own runtime dir; Wing reads a plist env), /health returns
it as `git_ref`, and estate-status compares it to the checkout it runs from.
This gate executes that comparison logic and Bone's stamp reader — not their
source text — and checks the deploy-side wiring is present.

Retro: with the compare_ref branch removed, a matching ref no longer reads as
`= checkout HEAD`; with Bone's stamp read pointed at a missing file it must say
`unknown`, never guess.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(path: Path, name: str, *extra_paths: Path):
    for p in extra_paths:
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── estate-status compare_ref: the reader that answers the doctrine ──────────

def _estate():
    return _load(REPO / "tools" / "estate-status.py", "_estate_status_gate",
                 REPO / "tools")


def _run_organ(monkeypatch, es, *, deployed, checkout):
    """Drive axis_organs for the bone organ with a stubbed payload + checkout
    ref, and return the single result line's text + level."""
    monkeypatch.setattr(es, "ORGANS", [
        {"name": "bone", "url": "http://x/api/health", "version_keys": ("git_ref",),
         "src": None, "repo_version": None, "compare_ref": True},
    ])
    monkeypatch.setattr(es, "http_json", lambda url, timeout=4: {"git_ref": deployed})
    monkeypatch.setattr(es, "git", lambda repo, *a, **k: checkout)
    res = es.Result()
    es.axis_organs(res)
    return [ln for ln in res.lines if ln.subject == "bone"]


def test_bone_and_wing_are_declared_with_a_ref_comparison():
    es = _estate()
    by_name = {o["name"]: o for o in es.ORGANS}
    for name in ("bone", "wing"):
        assert by_name[name].get("compare_ref") is True, (
            f"{name} does not compare its deployed ref — the permanent ? stands")
        assert by_name[name]["version_keys"] == ("git_ref",), (
            f"{name} reads the wrong health key for provenance")


def test_a_matching_ref_reads_as_in_sync(monkeypatch):
    es = _estate()
    rows = _run_organ(monkeypatch, es, deployed="abc123def456", checkout="abc123def456")
    assert rows, "no organ row emitted"
    text, level = rows[0].detail, rows[0].state
    assert "= checkout HEAD" in text and level == es.OK


def test_a_divergent_ref_is_flagged_not_equated(monkeypatch):
    es = _estate()
    rows = _run_organ(monkeypatch, es, deployed="oldsha000000", checkout="newsha111111")
    text, level = rows[0].detail, rows[0].state
    assert "≠ checkout" in text and level == es.DISAGREE, (
        "a deployed ref that differs from the checkout was silently equated — "
        "the repo is not the running system and the reader must say so")


def test_an_unstamped_ref_is_unreadable_never_a_guess(monkeypatch):
    es = _estate()
    rows = _run_organ(monkeypatch, es, deployed="unknown", checkout="abc123")
    text, level = rows[0].detail, rows[0].state
    assert level == es.UNREADABLE and "unstamped" in text, (
        "an organ that answers but was never stamped must read UNREADABLE, "
        "not compared against a ref it does not have")


# ── Bone's stamp reader: deploy-time provenance, not the live checkout ───────

def test_bone_reads_its_own_deploy_stamp(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="bone runtime deps absent here")
    pytest.importorskip("httpx", reason="bone runtime deps absent here")
    try:
        bone = _load(REPO / "files/anatomy/bone/main.py", "_bone_main_gate",
                     REPO / "files/anatomy/bone")
    except ImportError as exc:
        pytest.skip(f"bone main.py imports unavailable here: {exc}")
    stamp = tmp_path / "DEPLOYED_REF"
    stamp.write_text("deadbeef1234\n", encoding="utf-8")
    monkeypatch.setattr(bone, "DEPLOYED_REF_FILE", str(stamp))
    assert bone._deployed_ref() == "deadbeef1234"
    # Absent stamp → the honest word, never a crash and never a guess.
    monkeypatch.setattr(bone, "DEPLOYED_REF_FILE", str(tmp_path / "nope"))
    assert bone._deployed_ref() == "unknown"


# ── the deploy-side wiring exists (proven live only at converge) ─────────────

def test_the_converge_stamps_each_organ():
    """The value is computed once and reaches both organs. A behavioural test
    needs a converge; this pins the three wiring points so a rename cannot
    silently drop the stamp and return the permanent ? ."""
    main = (REPO / "main.yml").read_text(encoding="utf-8")
    assert "nos_deployed_ref" in main and "describe --always --dirty" in main, (
        "main.yml no longer resolves the deployed git ref")
    bone_role = (REPO / "roles/pazny.bone/tasks/main.yml").read_text(encoding="utf-8")
    assert "DEPLOYED_REF" in bone_role, "pazny.bone no longer stamps the ref"
    wing_plist = (REPO / "roles/pazny.wing/templates/wing.plist.j2").read_text(encoding="utf-8")
    assert "NOS_ORGAN_DEPLOYED_REF" in wing_plist, "pazny.wing plist no longer carries the ref"
