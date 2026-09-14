"""S7 — Tier-1 GDPR upsert is one PHP process, not one per service.

p=54800: ~50 `php bin/upsert-gdpr.php --id=` boots ~23s. The records tool
already emits a JSON array; one `--json=-` is the cut.
"""
from __future__ import annotations

import pathlib
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
POST = REPO / "roles" / "pazny.wing" / "tasks" / "post.yml"
APPS_POST = REPO / "roles" / "pazny.apps_runner" / "tasks" / "post.yml"
PHP = REPO / "files" / "anatomy" / "wing" / "bin" / "upsert-gdpr.php"


def test_tier1_gdpr_upsert_is_one_php_invocation():
    tasks = yaml.safe_load(POST.read_text(encoding="utf-8"))
    upsert = next(
        t for t in tasks
        if isinstance(t, dict) and "Upsert Tier-1 GDPR" in str(t.get("name", ""))
    )
    assert "loop" not in upsert, (
        f"{POST}: GDPR upsert still loops — that is one PHP boot per service"
    )
    cmd = str(
        (upsert.get("ansible.builtin.shell") or upsert.get("shell") or {}).get("cmd")
        or upsert.get("ansible.builtin.shell")
        or upsert.get("shell")
        or ""
    )
    assert "--json=-" in cmd
    assert "--id=" not in cmd


def test_apps_runner_still_upserts_one_object_with_id():
    text = APPS_POST.read_text(encoding="utf-8")
    assert "--id=app_{{ item.id }}" in text
    assert "--json=-" in text


def _dry(stdin: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["php", str(PHP), "--dry-run", "--json=-", *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.skipif(not PHP.is_file(), reason="upsert-gdpr.php missing")
def test_upsert_gdpr_empty_array_is_noop():
    r = _dry("[]")
    assert r.returncode == 0, r.stderr
    assert "OK upserted none" in r.stdout


@pytest.mark.skipif(not PHP.is_file(), reason="upsert-gdpr.php missing")
def test_upsert_gdpr_object_with_id_stays_one_record():
    r = _dry('{"name":"Documenso","purpose":"e-sign"}', "--id=app_documenso")
    assert r.returncode == 0, r.stderr
    assert "dry-run 1" in r.stdout
    assert "app_documenso" in r.stdout


@pytest.mark.skipif(not PHP.is_file(), reason="upsert-gdpr.php missing")
def test_upsert_gdpr_numeric_keys_with_id_are_not_a_batch():
    r = _dry('{"0":{"id":"a"},"1":{"id":"b"},"2":{"id":"c"}}', "--id=app_x")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "not an array" in r.stderr


@pytest.mark.skipif(not PHP.is_file(), reason="upsert-gdpr.php missing")
def test_upsert_gdpr_batch_array_without_id():
    r = _dry('[{"id":"svc_wing","name":"Wing"},{"id":"svc_bone","name":"Bone"}]')
    assert r.returncode == 0, r.stderr
    assert "dry-run 2" in r.stdout
    assert "svc_wing" in r.stdout and "svc_bone" in r.stdout
