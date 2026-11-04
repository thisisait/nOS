"""The codesign keychain dialog is asked in pre_tasks, before any role signs (2026-11-03).

A converge stopped two thirds in on "codesign wants to use the key" (pazny.medulla).
Pins the joint: tasks/preflight-keychain.yml is imported, tagged always, ahead of the
first include_role, and looks up the same identity the signing roles use.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_keychain_preflight_runs_before_first_role():
    pre = yaml.safe_load((REPO / "main.yml").read_text())[0]["pre_tasks"]
    idx = [i for i, t in enumerate(pre) if t.get("import_tasks") == "tasks/preflight-keychain.yml"]
    assert idx, "main.yml pre_tasks no longer imports tasks/preflight-keychain.yml"
    assert "always" in pre[idx[0]]["tags"]
    first_role = next(i for i, t in enumerate(pre) if "ansible.builtin.include_role" in t or "include_role" in t)
    assert idx[0] < first_role, "the keychain preflight must run before the first include_role"


def test_keychain_preflight_uses_the_signing_identity():
    defaults = yaml.safe_load((REPO / "roles/pazny.thalamus/defaults/main.yml").read_text())
    body = (REPO / "tasks/preflight-keychain.yml").read_text()
    assert f"default('{defaults['thalamus_signing_cn']}')" in body
    tail = defaults["thalamus_signing_keychain"].split("}}", 1)[1]
    assert f"~ '{tail}')" in body
