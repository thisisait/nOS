"""Anatomy gate — do not claim a WORM archive unless version-delete 403s.

The raw-archive-store row named the false-green: an S3 clone can accept Object
Lock headers and still delete the object. This file pins that shape. It does
not talk to a live host (CI has none). `tools/raw-archive-probe.py` is the
reader for a real endpoint.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PROBE = REPO / "tools" / "raw-archive-probe.py"
PLAN = REPO / "docs" / "plans" / "raw-archive-store.md"


def _probe():
    spec = importlib.util.spec_from_file_location("raw_archive_probe", PROBE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_claiming_worm_without_403_is_red():
    """The pre-fix lie: 'we have WORM' + delete 204. This MUST raise."""
    p = _probe()
    with pytest.raises(AssertionError, match="claimed WORM"):
        p.assert_worm_claim(True, 204)
    with pytest.raises(AssertionError, match="claimed WORM"):
        p.assert_worm_claim(True, None)


def test_403_is_the_only_green_worm_claim():
    p = _probe()
    p.assert_worm_claim(True, 403)
    p.assert_worm_claim(True, 409)
    p.assert_worm_claim(False, 204)


def test_accepted_lock_plus_successful_delete_is_non_honor():
    p = _probe()
    assert (
        p.classify(live=True, lock_status=200, put_status=200, delete_status=204)
        == p.NON_HONOR
    )
    assert (
        p.classify(live=True, lock_status=200, put_status=200, delete_status=403)
        == p.HONOR
    )
    assert (
        p.classify(live=True, lock_status=501, put_status=None, delete_status=None)
        == p.UNSUPPORTED
    )
    assert p.classify(live=False, lock_status=None, put_status=None, delete_status=None) == p.UNVERIFIED


def test_scripted_non_honor_is_what_the_false_green_looks_like():
    p = _probe()

    def transport(method, url, headers, body):
        hdrs = {}
        if method == "PUT" and "x-amz-object-lock-mode" in {k.lower() for k in headers}:
            hdrs["x-amz-version-id"] = "v1"
            return p.HttpResponse(200, hdrs, b"")
        if method == "DELETE":
            return p.HttpResponse(204, {}, b"")
        return p.HttpResponse(200, {}, b"")

    result = p.run_probe(
        access="AKIAFAKE",
        secret="secret",
        transport=transport,
        now=p.dt.datetime(2026, 9, 13, 12, 0, 0, tzinfo=p.dt.timezone.utc),
        bucket="raprobe-scripted",
    )
    assert result.verdict == p.NON_HONOR
    assert result.delete_status == 204
    with pytest.raises(AssertionError, match="claimed WORM"):
        p.assert_worm_claim(True, result.delete_status)


def test_scripted_honor_403s_the_version_delete():
    p = _probe()

    def transport(method, url, headers, body):
        if method == "PUT" and "x-amz-object-lock-mode" in {k.lower() for k in headers}:
            return p.HttpResponse(200, {"x-amz-version-id": "v1"}, b"")
        if method == "DELETE":
            return p.HttpResponse(403, {}, b"AccessDenied")
        return p.HttpResponse(200, {}, b"")

    result = p.run_probe(access="AKIAFAKE", secret="secret", transport=transport)
    assert result.verdict == p.HONOR
    p.assert_worm_claim(True, result.delete_status)


def test_dry_run_is_unverified():
    p = _probe()
    result = p.run_probe(dry_run=True)
    assert result.verdict == p.UNVERIFIED
    assert result.live is False


def test_plan_honor_claim_quotes_a_403():
    """If the plan says HONOR, it must cite a 403. A HONOR line without one is the lie."""
    text = PLAN.read_text()
    claim = None
    for line in text.splitlines():
        if line.startswith("CLAIM:"):
            claim = line.split(":", 1)[1].strip().split()[0]
            break
    assert claim in {"HONOR", "NON_HONOR", "UNSUPPORTED", "UNVERIFIED"}, (
        f"docs/plans/raw-archive-store.md needs a CLAIM: line, got {claim!r}"
    )
    if claim == "HONOR":
        assert "403" in text
        p = _probe()
        p.assert_worm_claim(True, 403)
