"""One journey through Wing's audit surface: events, the hash chain, GDPR records, wing.db.

Absorbed (2026-11-08, roadmap gate-diet-role-journeys); every assert is kept verbatim:
  test_purge_events                                   -> purge_*  section
  test_audit_badge_wiring                             -> badge section
  test_gov_audit_chain_toggle                         -> gov toggle section
  test_wing_db_busy_timeout                           -> busy timeout section
  test_gdpr_art30_php_python_parity                   -> art30 parity section
  test_gdpr_client_records_action                     -> client records section
  test_wing_event_post_failure_is_not_silent          -> event POST section
  test_a_consistent_chain_is_not_a_correctly_signed_one -> chain key section
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files/anatomy"))
import nos_identity as ni  # noqa: E402
from module_utils import nos_gdpr  # noqa: E402

PRESENTER = WING / "app/Presenters/GdprPresenter.php"
AUTOLOAD = WING / "vendor/autoload.php"

needs_php = pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")
needs_jq_openssl = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("openssl") is None,
    reason="functional harness needs jq + openssl on PATH",
)


# ── purge (test_purge_events) ──────────────────────────────────────────────
# GDPR storage-limitation purge: the real bin/purge-events.php against a
# throwaway SQLite DB — dry-run counts without deleting, a live run deletes only
# rows past the horizon, bad args fail. Skipped when php is unavailable.
PURGE_CLI = WING / "bin" / "purge-events.php"


def _seed_db(path: pathlib.Path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "ts TEXT NOT NULL, run_id TEXT NOT NULL, type TEXT NOT NULL)"
    )
    old = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    con.executemany(
        "INSERT INTO events (ts, run_id, type) VALUES (?, 'r', 'task_ok')",
        [(old,), (old,), (recent,)],  # 2 stale, 1 fresh
    )
    con.commit()
    con.close()


def _purge(*args: str):
    return subprocess.run(["php", str(PURGE_CLI), *args], capture_output=True, text=True)


def _count(path: pathlib.Path) -> int:
    con = sqlite3.connect(path)
    n = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    con.close()
    return n


@needs_php
def test_dry_run_counts_without_deleting(tmp_path):
    db = tmp_path / "wing.db"
    _seed_db(db)
    r = _purge(f"--db={db}", "--older-than-days=365", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "would purge 2 events" in r.stdout
    assert _count(db) == 3, "dry-run must not delete"


@needs_php
def test_live_run_deletes_only_stale(tmp_path):
    db = tmp_path / "wing.db"
    _seed_db(db)
    r = _purge(f"--db={db}", "--older-than-days=365")
    assert r.returncode == 0, r.stderr
    assert "Purged 2 events" in r.stdout
    assert _count(db) == 1, "only the fresh row survives"


@needs_php
def test_rejects_non_positive_days(tmp_path):
    db = tmp_path / "wing.db"
    _seed_db(db)
    assert _purge(f"--db={db}", "--older-than-days=0").returncode == 1
    assert _purge(f"--db={db}", "--older-than-days=abc").returncode == 1


@needs_php
def test_missing_args_fail(tmp_path):
    assert _purge("--older-than-days=365").returncode == 1


# ── badge (test_audit_badge_wiring) ────────────────────────────────────────
# Gov P1 UI: the audit-chain integrity badge is wired default-OFF — the verdict
# is set only behind the strict WING_AUDIT_CHAIN_ENABLED==='1' gate, @layout
# renders it only when set, the cached-verdict repo is DI-registered.

def test_basepresenter_strict_env_gate_and_inject():
    src = (WING / "app" / "Presenters" / "BasePresenter.php").read_text()
    assert "AuditChainRepository $auditChainForBadge" in src, "@inject repo missing"
    assert "getenv('WING_AUDIT_CHAIN_ENABLED') === '1'" in src, \
        "verdict must be gated on the STRICT '1' env check (no loose-truthy)"
    assert "$this->template->auditChainVerdict" in src


def test_layout_renders_badge_only_when_set():
    src = (WING / "app" / "Templates" / "@layout.latte").read_text()
    assert "isset($auditChainVerdict)" in src, "badge must be isset-guarded (hidden by default)"
    assert "['ok']" in src and "['known']" in src


def test_common_neon_registers_repo():
    assert "App\\Model\\AuditChainRepository" in (WING / "app" / "config" / "common.neon").read_text()


def test_repo_reads_cached_verdict_keys():
    src = (WING / "app" / "Model" / "AuditChainRepository.php").read_text()
    assert "last_verify_ok" in src and "last_verify_at" in src
    assert "audit_chain_meta" in src
    # cheap read, NOT a chain walk — must not pull in the verifier algorithm
    assert "rowHash" not in src and "AuditChain::" not in src


def test_verify_script_has_optin_write_flag():
    src = (WING / "bin" / "verify-audit-chain.php").read_text()
    assert "--write-verdict" in src
    assert "busyTimeout" in src, "verdict-write must be WAL-safe (busyTimeout)"


# ── gov toggle (test_gov_audit_chain_toggle) ───────────────────────────────
# The tamper-evident hash chain is default-OFF and a gov-local opt-in (with
# enforce_mfa + require_disk_encryption); post.yml runs a flag-gated anchor
# backfill. Parsed, not grepped: a commented-out line once satisfied a text assert.
GOV = REPO / "profiles" / "gov-local.yml"
POST = REPO / "roles" / "pazny.wing" / "tasks" / "post.yml"


def test_default_config_ships_chain_off():
    assert ni.default_config().get("wing_audit_chain_enabled") is False, \
        "default.config.yml must keep the audit chain OFF (normal run inert)"


def test_gov_local_three_gov_controls_all_true():
    doc = yaml.safe_load(GOV.read_text())
    assert doc.get("wing_audit_chain_enabled") is True
    assert doc.get("enforce_mfa") is True
    assert doc.get("require_disk_encryption") is True


def test_gov_local_no_longer_calls_audit_untogglable():
    # No single line both says "not yet togglable" AND mentions "audit".
    for line in GOV.read_text().splitlines():
        low = line.lower()
        assert not ("not yet togglable" in low and "audit" in low), \
            f"gov-local still describes the audit chain as un-togglable: {line!r}"


def test_post_yml_has_chain_gated_anchor_task():
    src = POST.read_text()
    assert "backfill-event-chain.php" in src, "post.yml must run the chain anchor backfill"
    assert "wing_audit_chain_enabled" in src, "the anchor task must be gated on the chain flag"


# ── busy timeout (test_wing_db_busy_timeout) ───────────────────────────────
# Scout 2026-07-15: two concurrent wing.db writers (breach-deadline-scan,
# dispatch-notifications) failed `database is locked` 4x/7d — WAL serializes
# writers and without a busy timeout the loser fails instantly. Every bin/*.php
# that opens wing.db read-write must set one.
BIN = WING / "bin"


def _writers():
    for f in sorted(BIN.glob("*.php")):
        src = f.read_text()
        sqlite_rw = re.search(r"new SQLite3\((?![^)]*READONLY)", src)
        pdo_sqlite = re.search(r"new PDO\('sqlite:", src)
        if sqlite_rw or pdo_sqlite:
            yield f, src


def test_every_wing_db_writer_sets_busy_timeout():
    missing = []
    for f, src in _writers():
        if not ("busyTimeout" in src or "busy_timeout" in src or "ATTR_TIMEOUT" in src):
            missing.append(f.name)
    assert not missing, (
        "wing.db writer scripts with NO busy timeout (add "
        "$db->busyTimeout(5000) for SQLite3, or "
        "$db->setAttribute(PDO::ATTR_TIMEOUT, 5) for PDO — else they fail "
        f"'database is locked' instantly under concurrent writers): {missing}"
    )


def test_at_least_the_known_writers_are_covered():
    # Sanity: the enumeration actually finds the scout-flagged writers.
    names = {f.name for f, _ in _writers()}
    for expected in ("dispatch-notifications.php", "breach-scan.php"):
        assert expected in names, f"{expected} no longer detected as a wing.db writer"


# ── art30 parity (test_gdpr_art30_php_python_parity) ───────────────────────
# D5 judge follow-up: Wing's live client-record view (PHP) and the Python
# register mapper derive id/slug/art30_role from the same party row in two
# languages; this RUNS both on a golden fixture. Skips without php or vendor.
PARTIES = [
    {"slug": "synthetic-firm", "legal_name": "Synthetic Consulting s.r.o.", "role": "own_firm"},
    {"slug": "synthetic-client-alfa", "legal_name": "Alfa Rizeni s.r.o. (synthetic)", "role": "client"},
    {"slug": "synthetic-counterparty", "legal_name": "Not GDPR-mapped a.s.", "role": "counterparty"},
    {"slug": "synthetic-nobody", "legal_name": "No Role Party"},
]

_HARNESS = r"""<?php
declare(strict_types=1);
require $argv[1]; // vendor/autoload.php
require $argv[2]; // GdprPresenter.php

$parties = json_decode(file_get_contents($argv[3]), true);

$presenter = (new ReflectionClass(App\Presenters\GdprPresenter::class))
    ->newInstanceWithoutConstructor();
$method = new ReflectionMethod(App\Presenters\GdprPresenter::class, 'controllerRecordFor');

$out = [];
foreach ($parties as $p) {
    $rec = $method->invoke($presenter, $p);
    $out[] = $rec === null ? null : [
        'id' => $rec['id'],
        'slug' => $rec['slug'],
        'art30_role' => $rec['art30_role'],
    ];
}
echo json_encode($out);
"""


def _php_records(parties: list[dict]) -> list[dict | None]:
    php = shutil.which("php")
    if php is None:
        pytest.skip("php binary not on PATH")
    if not AUTOLOAD.exists():
        pytest.skip("wing vendor/autoload.php missing — run `composer install` in files/anatomy/wing")
    harness = REPO / "tests/anatomy/_tmp_gdpr_parity_harness.php"
    harness.write_text(_HARNESS, encoding="utf-8")
    try:
        parties_path = REPO / "tests/anatomy/_tmp_gdpr_parity_parties.json"
        parties_path.write_text(json.dumps(parties), encoding="utf-8")
        try:
            proc = subprocess.run(
                [php, str(harness), str(AUTOLOAD), str(PRESENTER), str(parties_path)],
                capture_output=True, text=True, timeout=30,
            )
        finally:
            parties_path.unlink(missing_ok=True)
    finally:
        harness.unlink(missing_ok=True)
    assert proc.returncode == 0, f"PHP harness failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


def _py_records(parties: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in nos_gdpr.controller_records(parties)}


def test_art30_role_mapping_matches_between_php_and_python():
    php_out = _php_records(PARTIES)
    py_by_id = _py_records(PARTIES)

    # Same subset of parties gets a record on both sides.
    php_ids = {r["id"] for r in php_out if r is not None}
    assert php_ids == set(py_by_id), (
        f"PHP mapped {sorted(php_ids)}, Python mapped {sorted(py_by_id)} — "
        "the client/own_firm role filter has diverged between the two"
    )

    for rec in php_out:
        if rec is None:
            continue
        py_rec = py_by_id[rec["id"]]
        # Python's id is "party_<slug>" with no top-level slug; derive it.
        py_slug = py_rec["id"].removeprefix("party_")
        assert rec["slug"] == py_slug
        assert rec["art30_role"] == py_rec["art30_role"], (
            f"{rec['id']}: PHP says {rec['art30_role']!r}, "
            f"Python says {py_rec['art30_role']!r}"
        )


# ── client records (test_gdpr_client_records_action) ───────────────────────
# D5 unit 4 retro-red: GdprPresenter gained renderClientRecords and the KEAP
# client a by-slug fetch; the action writes nothing (D4 runtime-only rule) and
# startup() re-gates it at tier-managers so a consultant seat does not 403.
KEAP_CLIENT = WING / "app/Model/KeapCortexClient.php"
TEMPLATE = WING / "app/Templates/Gdpr/ClientRecords.latte"


def _method_body(src: str, name: str) -> str:
    m = re.search(rf"function {name}\([^)]*\)[^{{]*\{{", src)
    assert m, f"{name}() not found"
    start = m.end() - 1
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError(f"unbalanced braces in {name}()")


def test_keap_client_gained_a_fetch_row_by_slug_method():
    src = KEAP_CLIENT.read_text(encoding="utf-8")
    assert "public function tableRowBySlug(" in src


def test_gdpr_presenter_gained_the_client_records_action():
    src = PRESENTER.read_text(encoding="utf-8")
    assert "public function renderClientRecords(" in src
    assert TEMPLATE.is_file(), "no Latte template for the new action"


def test_client_records_action_never_writes_anything():
    """renderClientRecords + its helper touch no repository, no write: a refresh
    recomputes from KEAP every time (D4's runtime-only rule)."""
    src = PRESENTER.read_text(encoding="utf-8")
    body = _method_body(src, "renderClientRecords") + _method_body(src, "controllerRecordFor")
    forbidden = ["->insert(", "->update(", "->delete(", "file_put_contents", "fwrite(",
                 "this->repo->"]
    hits = [f for f in forbidden if f in body]
    assert not hits, f"renderClientRecords/controllerRecordFor writes: {hits}"


def test_rbac_reconciliation_client_records_is_reachable_at_tier_managers():
    """startup() drops the class-wide tier-1 gate to tier-managers (2) for the
    clientRecords action only."""
    src = PRESENTER.read_text(encoding="utf-8")
    assert "protected ?int $minAccessTier = 1;" in src, "renderDefault/DSAR/breaches still gate at tier-1"
    startup = _method_body(src, "startup")
    assert "'clientRecords'" in startup, "startup() has no per-action carve-out for clientRecords"
    assert "requireTier(2)" in startup, "clientRecords is not explicitly re-gated at tier-managers"


def test_client_records_scans_party_by_slug_not_all_records_into_all_records():
    """all_records() (the committed register) must never gain a caller here."""
    src = PRESENTER.read_text(encoding="utf-8")
    assert "all_records" not in src


# ── event POST (test_wing_event_post_failure_is_not_silent) ────────────────
# 2026-08-17 surveyor run: $0.96 ceremony exited 0 with ZERO events in wing.db —
# both HMAC POSTs died at curl exit 3 and the WARN printed caret debris as the
# "HTTP code". Functional: real pulse-run-agent.sh, stubbed curl/claude; a run
# that could not audit itself must exit 2 and name curl's exit.
SCRIPT = REPO / "files" / "anatomy" / "scripts" / "pulse-run-agent.sh"

CURL_STUB_EVENTS_DEAD = """#!/bin/bash
# Stub curl: token exchange succeeds; every Wing events POST dies the way the
# 2026-08-17 incident did — curl exit 3 before any request, no -w output,
# stderr ending in a caret line.
args="$*"
case "$args" in
  */application/o/token/*)
    printf '{"access_token":"stub-token"}\\n200\\n'
    exit 0 ;;
  */api/v1/events*)
    printf 'curl: (3) bad range in URL position 22:\\nhttp://[::1]:9000/api/v1/events\\n      ^\\n' >&2
    exit 3 ;;
  *)
    printf '000'
    exit 7 ;;
esac
"""

CURL_STUB_ALL_OK = """#!/bin/bash
args="$*"
case "$args" in
  */application/o/token/*)
    printf '{"access_token":"stub-token"}\\n200\\n'
    exit 0 ;;
  */api/v1/events*)
    printf '{"ok":true}\\n201\\n'
    exit 0 ;;
  *)
    printf '201'
    exit 0 ;;
esac
"""

CLAUDE_STUB = """#!/bin/bash
printf '{"result":"stub ceremony report","usage":{"input_tokens":10,"output_tokens":20,"cache_read_input_tokens":0},"total_cost_usd":0.01}'
"""


def _run_agent(tmp_path: pathlib.Path, curl_stub: str) -> subprocess.CompletedProcess:
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    for name, body in (("curl", curl_stub), ("claude", CLAUDE_STUB)):
        p = stub_bin / name
        p.write_text(body)
        p.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{stub_bin}:{env['PATH']}",
            "NOS_AUTHENTIK_URL": "http://auth.stub.local",
            "NOS_AGENT_NAME": "gate-stub",
            "NOS_AGENT_CLIENT_SECRET": "stub-secret",
            "NOS_AGENT_TASK": "say nothing",
            "WING_API_URL": "http://127.0.0.1:9",  # never contacted: curl is stubbed
            "WING_API_TOKEN": "stub",
            "WING_EVENTS_HMAC_SECRET": "stub",
            "NOS_AGENT_LOCK_DIR": str(tmp_path / "agent.lock"),
        }
    )
    env.pop("NOS_AGENT_PROFILE", None)
    env.pop("ANTHROPIC_BASE_URL", None)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


@needs_jq_openssl
def test_dead_audit_posts_escalate_a_clean_run_to_exit_2(tmp_path):
    res = _run_agent(tmp_path, CURL_STUB_EVENTS_DEAD)
    assert res.returncode == 2, (
        "ceremony succeeded but both audit POSTs died — the runner must exit 2 "
        f"(Wing error), got {res.returncode}\nstderr:\n{res.stderr}"
    )
    assert "invisible to the audit surface" in res.stderr


@needs_jq_openssl
def test_the_warn_reports_curl_not_stderr_debris(tmp_path):
    res = _run_agent(tmp_path, CURL_STUB_EVENTS_DEAD)
    for line in res.stderr.splitlines():
        if "Wing event POST returned HTTP" in line:
            code = line.rsplit("HTTP", 1)[1].strip()
            assert code.isdigit() and len(code) == 3, (
                f"WARN presented non-status text as an HTTP code: {line!r}"
            )
    assert "curl exit 3" in res.stderr


@needs_jq_openssl
def test_a_clean_run_with_landed_events_still_exits_0(tmp_path):
    res = _run_agent(tmp_path, CURL_STUB_ALL_OK)
    assert res.returncode == 0, (
        f"regression: healthy path no longer exits 0 (got {res.returncode})\n"
        f"stderr:\n{res.stderr}"
    )
    assert "invisible to the audit surface" not in res.stderr


# ── chain key (test_a_consistent_chain_is_not_a_correctly_signed_one) ──────
# Live 2026-08-09: 173948 rows signed for fifteen green nights with the RETIRED
# (leaked) key — verify-audit-chain.php checked consistency, never WHICH key.
# Pins: tail key vs $keyRing[0], a stale key exits non-zero, and the cached badge
# verdict includes it (computed before the write). Reads comment-stripped source.
VERIFY = WING / "bin/verify-audit-chain.php"


def _chain_code() -> str:
    """The file with comments and docblocks removed."""
    src = VERIFY.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)      # block + docblocks
    src = re.sub(r"^\s*//.*$", "", src, flags=re.M)      # whole-line //
    src = re.sub(r"(?<![:'\"])//[^\n'\"]*$", "", src, flags=re.M)   # trailing //
    return src


def test_the_verifier_exists():
    assert VERIFY.exists(), f"{VERIFY} is gone — the control has no verifier"


def test_the_tail_key_is_compared_against_the_current_one():
    src = _chain_code()
    assert re.search(r"\$keyRing\s*\[\s*0\s*\]", src), (
        "nothing in verify-audit-chain.php compares anything to $keyRing[0], the "
        "CURRENT key. Without that the chain can be entirely signed with a "
        "retired credential and still verify — which it was, for 173948 rows "
        "across fifteen nights of green.")
    assert re.search(r"\$tailIsCurrent", src), (
        "the tail-key verdict has no name in the code; the check that catches a "
        "writer stuck on a retired key must exist as its own decision")


def test_a_stale_tail_key_is_not_a_success():
    src = _chain_code()
    m = re.search(r"if\s*\(\s*!\s*\$tailIsCurrent\s*\)(.{0,900})", src, flags=re.S)
    assert m, "no branch acts on $tailIsCurrent — computing it and ignoring it is worse than not computing it"
    branch = m.group(1)
    assert re.search(r"exit\s*\(\s*[1-9]", branch), (
        "a chain signed with a retired key exits 0 — the nightly job would keep "
        "reporting success for the exact condition this check was added to find")


def test_the_cached_verdict_agrees_with_the_exit_code():
    """The badge and the exit code must be one verdict, not two."""
    src = _chain_code()
    m = re.search(r"\$verdictOk\s*=\s*([^;]+);", src)
    assert m, "no $verdictOk assignment found — the cached verdict is what the UI renders"
    expr = m.group(1)
    assert "$tailIsCurrent" in expr, (
        "$verdictOk is computed from $break alone, so the Wing header badge would "
        "render a calm green while this process exits 2 on a stale key. Fold "
        "$tailIsCurrent into it — and compute it BEFORE the write, which is where "
        "the first draft of this fix had it wrong.")


def test_the_stale_key_check_is_computed_before_the_verdict_is_written():
    src = _chain_code()
    where_computed = src.find("$tailIsCurrent =")
    where_written = src.find("$verdictOk =")
    assert where_computed != -1 and where_written != -1
    assert where_computed < where_written, (
        "$tailIsCurrent is computed after $verdictOk is written, so the cached "
        "verdict cannot possibly include it")
