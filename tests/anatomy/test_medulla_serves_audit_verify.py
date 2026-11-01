"""The medulla answers GET /api/v1/audit/verify exactly as Api\\AuditPresenter does (ssot/doctrine/medulla.md §5).

WHY (read set [audit]). The medulla never holds WING_EVENTS_HMAC_SECRET: the role renders a non-secret
MEDULLA_AUDIT_CHAIN=on|off from the value Wing gets, and without it the medulla says 503, never chain:'off'
(a stale 'off' would hide a tamper-evident chain). Parity is measured as for the Pulse reads: the real
presenter and the medulla answer one scratch wing.db per verdict state x every bearer.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_pulse_reads", REPO / "tests/anatomy/test_medulla_serves_pulse_reads.py")
p = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p)
m = p.m

SECRET = "FAKE_audit_chain_secret_never_leaks"
URL = "/api/v1/audit/verify"
_pre, _rest = p._PHP.split("  $p = $name", 1)
_PHP = (_pre + "  $p = new App\\Presenters\\Api\\AuditPresenter(new App\\Model\\AuditChainRepository($db));\n"
        + _rest[_rest.index("  $p->tokenRepo"):])

#: state -> (MEDULLA_AUDIT_CHAIN, audit_chain_meta rows, the verdict a wing.read token sees)
STATES = {"chain off": ("off", {}, {"chain": "off", "ok": True}),
          "chain on, no verdict": ("on", {}, {"chain": "on", "known": False, "ok": None}),
          "ok=1": ("on", {"last_verify_ok": "1", "last_verify_at": "2026-11-01T03:00:00Z"}, {"chain": "on", "ok": True}),
          "ok=0": ("on", {"last_verify_ok": "0", "last_verify_at": "2026-11-01T04:00:00Z"}, {"chain": "on", "ok": False})}


def test_the_caddyfile_moves_only_the_audit_get():
    block = re.search(r"@medulla_read_audit \{(.*?)\n    \}", p._render(["audit"]), re.S).group(1)
    assert block.split() == ["method", "GET", "path", "/api/v1/audit/verify"], block
    assert "@medulla_read_audit" not in p._render(["pulse"])


def test_the_env_names_the_flag_and_never_the_secret():
    # AuditChain::chainKey(): getenv() ?: '' — unset, '' and '0' are all chain off.
    for over, want in (({"wing_events_hmac_secret": SECRET}, "on"), ({"bone_secret": SECRET}, "on"),
                       ({"wing_events_hmac_secret": ""}, "off"), ({}, "off"), ({"wing_events_hmac_secret": "0"}, "off")):
        envfile, plist = m._thalamus_env(medulla_read_routes=["audit"], **over)
        assert f"MEDULLA_AUDIT_CHAIN={want}" in envfile.splitlines() and plist.get("MEDULLA_AUDIT_CHAIN") == want, (over, envfile)
        for text in (envfile, json.dumps(plist)):
            assert "WING_EVENTS_HMAC_SECRET" not in text and SECRET not in text, over
    envfile, plist = m._thalamus_env(medulla_read_routes=[])
    assert "MEDULLA_AUDIT_CHAIN" not in envfile and "MEDULLA_AUDIT_CHAIN" not in plist


@m.needs_cargo
@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
@pytest.mark.skipif(not m.AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")
@pytest.mark.skipif(not shutil.which("sqlite3"), reason="sqlite3 seeds the scratch wing.db")
def test_php_and_the_medulla_answer_every_verdict_the_same(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_HALT_FILE", str(tmp_path / "halt"))
    monkeypatch.delenv("WING_EVENTS_HMAC_SECRET", raising=False)
    subprocess.run(["php", str(m.WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    p._seed(tmp_path / "wing.db")
    exe = m._medulla(tmp_path)
    responses = m.yaml.safe_load(m.OPENAPI.read_text(encoding="utf-8"))["paths"][URL]["get"]["responses"]
    cases = [{"url": URL, "headers": h, "auth": a} for a, h in p.AUTH.items()]
    codes: set[int] = set()
    for i, (state, (flag, meta, verdict)) in enumerate(STATES.items()):
        db = tmp_path / f"wing-{i}.db"
        shutil.copy2(tmp_path / "wing.db", db)
        rows = "".join(f"INSERT OR REPLACE INTO audit_chain_meta (k, v) VALUES ('{k}', '{v}');" for k, v in meta.items())
        subprocess.run(["sqlite3", str(db)], input=rows, text=True, check=True)
        php_env = {k: v for k, v in os.environ.items() if not k.startswith("WING_EVENTS_HMAC_SECRET")}
        if flag == "on":
            php_env["WING_EVENTS_HMAC_SECRET"] = SECRET
        r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _PHP, str(m.AUTOLOAD), str(db), json.dumps(cases)],
                           capture_output=True, text=True, timeout=300, check=False, cwd=m.WING, env=php_env)
        assert r.returncode == 0, (r.stdout + r.stderr)[-4000:]
        php = json.loads(r.stdout)
        monkeypatch.setenv("MEDULLA_AUDIT_CHAIN", flag)
        proc, port = m._serve(exe, db)
        try:
            got = [p._medulla_get(port, c["url"], c["headers"]) for c in cases]
        finally:
            proc.kill()
            proc.wait()
        for c, want, (code, ctype, body) in zip(cases, php, got):
            where = f"{state} as {c['auth']}"
            assert str(code) in responses, f"{where}: {code} is not in wing.openapi.yml"
            assert SECRET not in body and SECRET not in want["body"], f"the secret left on {where}"
            assert (code, ctype) == (want["code"], "application/json; charset=utf-8"), f"{where}: medulla {code} {ctype} {body} / php {want}"
            assert json.loads(body) == json.loads(want["body"]), f"{where}:\nmedulla {body}\nphp     {want['body']}"
            codes.add(code)
        seen = json.loads(got[list(p.AUTH).index("wing.read")][2])
        assert {k: seen.get(k) for k in verdict} == verdict, (state, seen)
    # The seed reaches every outcome; a fixture gone blind would pass the comparison vacuously.
    assert codes == {200, 401, 403}, codes


@m.needs_cargo
@pytest.mark.skipif(not shutil.which("php"), reason="php builds the schema")
def test_an_unrendered_flag_is_a_503_the_contract_names(tmp_path, monkeypatch):
    # Wing never says 503 here, the medulla does on Wing's path: the contract must name it for a caller.
    monkeypatch.setenv("NOS_HALT_FILE", str(tmp_path / "halt"))
    monkeypatch.delenv("MEDULLA_AUDIT_CHAIN", raising=False)
    subprocess.run(["php", str(m.WING / "bin/init-db.php"), f"--data-dir={tmp_path}"], capture_output=True, check=True, timeout=60)
    p._seed(tmp_path / "wing.db")
    proc, port = m._serve(m._medulla(tmp_path), tmp_path / "wing.db")
    try:
        code, _, body = p._medulla_get(port, URL, p.AUTH["wing.read"])
    finally:
        proc.kill()
        proc.wait()
    assert code == 503 and "UNKNOWN" in json.loads(body)["error"], (code, body)
    assert "503" in m.yaml.safe_load(m.OPENAPI.read_text(encoding="utf-8"))["paths"][URL]["get"]["responses"]
