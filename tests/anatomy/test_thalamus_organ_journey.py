"""One journey through the thalamus organ: the backend its cell binds, the ledger it
writes beside Wing's, the env its two service managers hand it, and the reader that
judges it on a systemd host.

Absorbed (2026-11-10, roadmap gate-diet), one section each:
  test_thalamus_binding, test_thalamus_ledger_fields, test_thalamus_env_matches_plist,
  test_thalamus_reads_a_systemd_host.
Every assert of those files survives here with the same inputs and expectations.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import shutil
import socket
import subprocess
import tempfile

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CRATE = REPO / "files/anatomy/thalamus/thalamus"
needs_cargo_binding = pytest.mark.skipif(not shutil.which("cargo"), reason="cargo runs the resolver")
needs_cargo_ledger = pytest.mark.skipif(not shutil.which("cargo"), reason="cargo runs the ledger writer")


# ── test_thalamus_binding ───────────────────────────────────────────────────
# The thalamus runs a model without Wing, so it resolves its cell's binding the
# way BindingResolver.php does; a drifted resolver routes a person's rows to a
# backend iris's Article-30 record does not cover. Rust cases read the REAL register.

IRIS = REPO / "files/anatomy/agents/iris/agent.yml"
REGISTER = REPO / "state/habitat/llm-backends.yml"


def test_the_iris_cell_binds_to_the_eu_row_by_default():
    """Ruling 2026-10-12: iris binds mistral-eu. Ruling 2026-10-14: a host may choose the on-device row
    instead (iris_backend: ollama) — chosen explicitly, never as a fallback. Ruling 2026-10-17: also the
    non-EU anthropic-api / minimax-api rows, which gate 8 serves only at gdpr_posture: none."""
    doc = yaml.safe_load(IRIS.read_text())
    assert doc["name"] == "iris"
    assert doc["model"]["backend"] == "mistral-eu"
    assert doc["model"]["backends_allowed"] == ["mistral-eu", "ollama", "anthropic-api", "minimax-api"]
    non_eu = {"anthropic-api", "minimax-api"}
    assert doc["gdpr"]["transfers_outside_eu"] is False, (
        "without it a disarmed mistral-eu degrades iris to the hosted default")
    tier = re.search(r"\b(haiku|sonnet|opus|vision)\b", doc["model"]["primary"])
    rows = yaml.safe_load(REGISTER.read_text())["backends"]
    for b in doc["model"]["backends_allowed"]:
        assert tier and rows[b]["model_env"].get(tier[1]), f"{doc['model']['primary']} has no model on {b}"
        assert rows[b]["residency"]["eu"] is (b not in non_eu), f"{b}: residency is not what the ruling says"
    names = [p["name"] for p in doc["gdpr"]["processors"]]
    for b in doc["model"]["backends_allowed"]:
        assert any(rows[b]["processor_match"] in n for n in names), f"no processor of iris names the {b} row"
    assert all(any(rows[b]["processor_match"] in n for b in doc["model"]["backends_allowed"]) for n in names), (
        f"every processor iris names must belong to an allowed row, got {names}")


def test_the_rust_cases_read_the_register_not_a_copy():
    src = (CRATE / "tests/binding.rs").read_text()
    assert "state/habitat/llm-backends.yml" in src
    assert not list(CRATE.rglob("llm-backends*.yml")), "a copied register drifts from the real one"


@needs_cargo_binding
def test_the_resolver_runs():
    r = subprocess.run(["cargo", "test", "--quiet", "--manifest-path", str(CRATE / "Cargo.toml"),
                        "--test", "binding"], capture_output=True, text=True, timeout=600, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    n = re.search(r"(\d+) passed", r.stdout)
    assert n and int(n[1]) >= 13, r.stdout


# ── test_thalamus_ledger_fields ─────────────────────────────────────────────
# A function moved from AgentKit into the thalamus is compared row by row with
# Wing's ledger: every column must exist in Wing's table by name and type, Wing's
# required columns be filled, every event type be in the contract. Oracles are
# Wing's SQL and event-types.yml, never a copied list; `cargo test ledger` runs too.

LEDGER = CRATE / "src/ledger.rs"
WING_SQL = REPO / "files/anatomy/wing/db/schema-extensions.sql"
EVENT_TYPES = REPO / "files/anatomy/contracts/event-types.yml"
#: thalamus table -> the Wing table it is a subset of
MIRROR = {"sessions": "agent_sessions", "events": "events"}
CONSTRAINT = re.compile(r"^(PRIMARY|UNIQUE|FOREIGN|CHECK|CONSTRAINT)\b")
TYPE_ARM = re.compile(r'=>\s*"([a-z][a-z0-9_.]*)"')


def _tables(sql: str) -> dict[str, dict[str, str]]:
    """{table: {column: declaration}} from every CREATE TABLE in the text."""
    sql = re.sub(r"--[^\n]*", "", sql)
    out: dict[str, dict[str, str]] = {}
    for name, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\s*\);", sql, re.S):
        cols = {}
        for line in body.split("\n"):
            line = line.strip().rstrip(",")
            if line and not CONSTRAINT.match(line):
                col, decl = line.split(None, 1)
                cols[col] = decl
        out[name] = cols
    return out


def _strays(rust: str, wing: str) -> list[str]:
    ours, theirs, bad = _tables(rust), _tables(wing), []
    if set(ours) != set(MIRROR):
        bad.append(f"ledger tables {sorted(ours)} != {sorted(MIRROR)}")
    for t, cols in ours.items():
        w = theirs.get(MIRROR.get(t, ""), {})
        for col, decl in cols.items():
            if col not in w:
                bad.append(f"{t}.{col}: not a column of Wing {MIRROR.get(t)}")
            elif decl.split()[0] != w[col].split()[0]:
                bad.append(f"{t}.{col}: {decl.split()[0]} here, {w[col].split()[0]} in Wing")
        for col, decl in w.items():
            if "NOT NULL" in decl and "DEFAULT" not in decl and col not in cols:
                bad.append(f"{t}: misses Wing's required {MIRROR[t]}.{col}")
    return bad


def _unlisted(rust: str) -> tuple[set[str], set[str]]:
    used = set(TYPE_ARM.findall(rust))
    return used, used - set(yaml.safe_load(EVENT_TYPES.read_text(encoding="utf-8"))["types"])


def _rust() -> str:
    return LEDGER.read_text(encoding="utf-8")


def test_every_ledger_column_is_a_wing_column():
    assert not _strays(_rust(), WING_SQL.read_text(encoding="utf-8"))


def test_a_planted_column_goes_red():
    planted = _rust().replace("CREATE TABLE IF NOT EXISTS sessions (",
                              "CREATE TABLE IF NOT EXISTS sessions (\n    planted_col TEXT,", 1)
    assert "sessions.planted_col: not a column of Wing agent_sessions" in _strays(
        planted, WING_SQL.read_text(encoding="utf-8"))


def test_every_event_type_is_in_the_contract():
    used, unlisted = _unlisted(_rust())
    assert len(used) >= 7, f"the type extractor matched only {sorted(used)}"
    assert not unlisted


def test_a_planted_type_goes_red():
    _, unlisted = _unlisted(_rust().replace('=> "agent_message"', '=> "agent_chatter"', 1))
    assert unlisted == {"agent_chatter"}


@needs_cargo_ledger
def test_the_writer_runs():
    r = subprocess.run(["cargo", "test", "--quiet", "--manifest-path", str(CRATE / "Cargo.toml"), "ledger"],
                       capture_output=True, text=True, timeout=600, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert re.search(r"[1-9]\d* passed", r.stdout), r.stdout


# ── test_thalamus_env_matches_plist ─────────────────────────────────────────
# 2026-10-21 (spark1): iris_plan hybrid rendered no NOS_CORTEX_URL or
# NOS_IRIS_INTENTS into thalamus.env, so hybrid on Linux planned nothing. The two
# templates are one service on two managers: same names but the manager's own.
# CEILING: names, not the conditions around them.

T = REPO / "roles" / "pazny.thalamus" / "templates"
# systemd hands thalamus a shared socket and relay host; launchd sockets live in the plist's own keys.
# NOS_HALT_FILE / NOS_LOOPS_PAUSED_FILE: only a system-user host (Linux) moves the set-points out of ~/.nos
LINUX_ONLY = {"THALAMUS_RELAY_HOST", "THALAMUS_SOCKET", "THALAMUS_SOCKET_SHARED", "NOS_HALT_FILE", "NOS_LOOPS_PAUSED_FILE"}


def _plist() -> set[str]:
    return set(re.findall(r"<key>([A-Z][A-Z0-9_]+)</key>", (T / "thalamus.plist.j2").read_text(encoding="utf-8")))


def _env() -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]+)=", (T / "thalamus.env.j2").read_text(encoding="utf-8"), re.M))


def test_linux_env_sets_every_plist_variable():
    missing = sorted(_plist() - _env())
    assert not missing, f"thalamus.env.j2 never sets {missing}, which thalamus.plist.j2 does"


def test_linux_only_names_are_the_known_ones():
    extra = sorted(_env() - _plist() - LINUX_ONLY)
    assert not extra, f"thalamus.env.j2 sets {extra}, which the plist does not: add them there or to LINUX_ONLY"


def test_hybrid_wires_the_organ_on_linux():
    env = (T / "thalamus.env.j2").read_text(encoding="utf-8")
    assert re.search(r"iris_plan[^%]*in \[\s*'cortex',\s*'hybrid'\s*\]", env), \
        "thalamus.env.j2 wires NOS_CORTEX_URL only for iris_plan cortex, so hybrid plans nothing"


# ── test_thalamus_reads_a_systemd_host ──────────────────────────────────────
# On the DGX Spark tools/thalamus-status.py read every line UNKNOWN (launchd only)
# and the socket RED: the Linux role serves a SHARED 0666 socket by design. Pinned:
# path and mode from the unit's env, job from systemctl, starts from the journal.

TOOL = REPO / "tools" / "thalamus-status.py"


def _reader():
    spec = importlib.util.spec_from_file_location("_thal_linux", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_shared_socket_is_judged_against_its_own_mode():
    r = _reader()
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "t.sock"
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(str(path))
        srv.listen(1)
        # judge_socket proves serving with a connect() nobody accepts here; drain the backlog after
        # each judgement, or listen(1) on Darwin refuses the next connect (red on macOS, green on Linux).
        srv.settimeout(1)

        def judged(*args):
            v = r.judge_socket(*args)
            try:
                srv.accept()[0].close()
            except OSError:
                pass
            return v["state"]

        try:
            os.chmod(path, 0o666)
            assert judged(path, 0o666) == "OK"
            assert judged(path) == "RED", "a private socket at 0666 is open to every login"
            os.chmod(path, 0o600)
            assert judged(path) == "OK"
        finally:
            srv.close()


def test_collect_on_linux_reads_unit_journal_and_systemctl(monkeypatch, tmp_path):
    r = _reader()
    sock = tmp_path / "s.sock"
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    monkeypatch.setattr(r.nos_host, "SYSTEM", "Linux")
    monkeypatch.delenv("NOS_THALAMUS_SOCKET", raising=False)
    monkeypatch.delenv("NOS_THALAMUS_LEDGER", raising=False)
    monkeypatch.setattr(r.nos_host, "service_definition", lambda label: {
        "path": "/h/.config/systemd/user/eu.thisisait.nos.thalamus.service",
        "argv": ["/h/thalamus/bin/thalamus", "serve", "--data-dir", str(data)],
        "env": {"THALAMUS_SOCKET": str(sock), "THALAMUS_SOCKET_SHARED": "1", "THALAMUS_RELAY_SECRET": "x"}})
    monkeypatch.setattr(r.nos_host, "service_state", lambda label: {
        "loaded": True, "running": True, "pid": 7, "detail": "loaded, active/running, pid 7",
        "source": "systemctl --user show eu.thisisait.nos.thalamus.service"})
    monkeypatch.setattr(r.nos_host, "service_log", lambda label, **k: (
        ["thalamus: model bound ollama-x", "thalamus: relay closed"], "journalctl --user -u eu.thisisait.nos.thalamus.service"))
    rows = {x["check"]: x for x in r.collect()}
    assert rows["socket"]["source"] == str(sock), "the path the unit's env names"
    assert rows["systemd"]["state"] == "OK" and "launchd" not in rows
    assert rows["model"]["state"] == "OK" and rows["model"]["source"].startswith("journalctl")
    assert rows["relay"]["state"] == "RED", "a secret in the env file and a closed door"
    assert rows["ledger"]["source"] == str(data / "ledger.db"), "--data-dir from ExecStart"
    # Ruled 2026-11-08 (thalamus-linux-deciders): on Linux the face relay decides, socket peers record only.
    assert rows["deciders"]["state"] == "OK" and "face relay decides" in rows["deciders"]["detail"], rows["deciders"]


def test_an_unreadable_journal_or_unit_is_unknown(monkeypatch):
    r = _reader()
    monkeypatch.setattr(r.nos_host, "SYSTEM", "Linux")
    monkeypatch.delenv("NOS_THALAMUS_LEDGER", raising=False)
    monkeypatch.setattr(r.nos_host, "service_definition", lambda label: None)
    monkeypatch.setattr(r.nos_host, "service_state", lambda label: None)
    monkeypatch.setattr(r.nos_host, "service_log", lambda label, **k: None)
    rows = {x["check"]: x for x in r.collect()}
    for check in ("socket", "systemd", "model", "relay", "deciders", "ledger", "last session"):
        assert rows[check]["state"] == "UNKNOWN", (check, rows[check])


def test_who_may_decide_is_said_per_platform(tmp_path):
    """A set list on Linux refuses every decision (SO_PEERCRED names no binary); on macOS a listed
    path that names no file admits nobody. Both are red; the honest default is green and says who decides."""
    j = _reader().judge_deciders
    assert j("/h/thalamus/bin/thalamus", True, True, "u")["state"] == "RED"
    assert j("", False, True, "u")["state"] == "OK" and "no face relay" in j("", False, True, "u")["detail"]
    real = tmp_path / "nOS"
    real.write_text("")
    assert j(f"{real}:/nowhere/medulla", True, False, "p")["state"] == "RED"
    ok = j(str(real), True, False, "p")
    assert ok["state"] == "OK" and "nOS" in ok["detail"] and "face relay" in ok["detail"], ok
    assert j(None, True, False, "p")["state"] == "UNKNOWN"
