"""The thalamus on the host: one role builds it, one plist runs `thalamus serve`.

Increment 8 of the thalamus slice-1 definition. The role reuses the receptor's identity map and
never renders one of its own (operator ruling 1: one map, one renderer). The
proxy secret lives only in the 0600 plist env, never in ProgramArguments. The
reader tools/thalamus-status.py says OK only for what it read, UNKNOWN else.

Offline: the plist is rendered with jinja2, the reader is judged on fixtures.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import plistlib
import socket
import sqlite3
import sys
import tempfile

import jinja2
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles" / "pazny.thalamus"
READER = REPO / "tools" / "thalamus-status.py"


def _tasks() -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())


def _plist(**over) -> dict:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = bool
    ctx = {"thalamus_launchd_label": "eu.thisisait.nos.thalamus", "thalamus_bin": "/h/thalamus/bin/thalamus",
           "thalamus_home": "/h/thalamus", "thalamus_log_dir": "/h/thalamus/log", "nos_main_checkout": "/repo",
           "nos_tools_venv": "/h/.nos/tools-venv", "homebrew_prefix": "/opt/homebrew",
           "ansible_facts": {"env": {"HOME": "/h"}}, "keap_proxy_shared_secret": "s3cret", "keap_port": 8091,
           "ollama_enabled": True, "ollama_model": "qwen3:14b", "ollama_small_model": "hermes3:8b",
           "authentik_rbac_tiers": _default_config()["authentik_rbac_tiers"], **over}
    text = env.from_string((ROLE / "templates" / "thalamus.plist.j2").read_text()).render(**ctx)
    return plistlib.loads(text.encode())


def _default_config() -> dict:
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity
    return nos_identity.default_config()


def test_install_thalamus_defaults_false():
    assert _default_config()["install_thalamus"] is False


def test_the_plist_names_the_tier_one_groups_from_the_rbac_tiers():
    """serve answers approvals/red-status only to tier 1; the groups come from one list, not Rust."""
    tier1 = next(t for t in _default_config()["authentik_rbac_tiers"] if t["tier"] == 1)["groups"]
    assert _plist()["EnvironmentVariables"]["NOS_TIER1_GROUPS"] == ",".join(tier1)
    src = "".join(p.read_text() for p in (REPO / "files/anatomy/thalamus/thalamus/src").glob("*.rs"))
    assert not [g for g in tier1 if f'"{g}"' in src], "a tier-1 group name is hard-coded in Rust"


def test_the_plist_runs_serve_and_keeps_the_secret_out_of_argv():
    p = _plist()
    assert p["ProgramArguments"] == ["/h/thalamus/bin/thalamus", "serve"]
    env = p["EnvironmentVariables"]
    assert env["KEAP_PROXY_SHARED_SECRET"] == "s3cret"
    assert env["KEAP_URL"] == "http://127.0.0.1:8091"
    assert env["NOS_REPO_ROOT"] == "/repo"
    assert env["NOS_ARMED_BACKENDS"] == "ollama" and env["NOS_LOCAL_MODEL"] == "qwen3:14b"
    assert "s3cret" not in " ".join(p["ProgramArguments"])
    assert _plist(ollama_enabled=False)["EnvironmentVariables"]["NOS_ARMED_BACKENDS"] == ""


def test_the_plist_is_0600_and_the_logs_and_data_0700():
    tasks = _tasks()
    plist = next(t for t in tasks if "plist" in t.get("name", "").lower() and "ansible.builtin.template" in t)
    assert plist["ansible.builtin.template"]["mode"] == "0600"
    dirs = next(t for t in tasks if "directories" in t.get("name", ""))
    modes = {i["path"]: i["mode"] for i in dirs["loop"]}
    assert modes["{{ thalamus_log_dir }}"] == "0700" and modes["{{ thalamus_home }}/data"] == "0700", modes


def test_the_role_renders_no_identity_map_of_its_own():
    """Ruling 1: the receptor role is the one renderer of ~/.nos/identity-map.yml."""
    writes = [str(t.get(m, {})) for t in _tasks() for m in
              ("ansible.builtin.template", "ansible.builtin.copy", "ansible.builtin.file", "ansible.builtin.lineinfile")]
    assert not [w for w in writes if "identity" in w], "only pazny.receptor renders the map"
    assert not list(ROLE.glob("templates/identity*"))


def test_the_role_refuses_a_receptor_map_the_binary_does_not_read():
    """serve.rs fixes ~/.nos/identity-map.yml; an overridden receptor_identity_map would refuse everyone."""
    asserts = [str(t["ansible.builtin.assert"]) for t in _tasks() if "ansible.builtin.assert" in t]
    assert any("receptor_identity_map" in a and ".nos/identity-map.yml" in a for a in asserts), asserts
    rs = (REPO / "files/anatomy/thalamus/thalamus/src/serve.rs").read_text()
    assert 'IDENTITY_MAP: &str = ".nos/identity-map.yml"' in rs


def test_the_build_is_locked_and_off_the_checkout():
    """--locked: the converge builds the Cargo.lock dependabot watches, not a fresh resolve."""
    build = next(t for t in _tasks() if "install thalamus binary" in t.get("name", "").lower())
    sh = build["ansible.builtin.shell"]
    assert "--locked" in sh and "--release" in sh and "CARGO_TARGET_DIR" in sh, sh


def _reader():
    spec = importlib.util.spec_from_file_location("thalamus_status", READER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_reader_judges_the_socket_by_kind_and_mode():
    r = _reader()
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        path = pathlib.Path(d) / "t.sock"
        assert r.judge_socket(path)["state"] == "RED"            # absent
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(path))
        os.chmod(path, 0o644)
        assert r.judge_socket(path)["state"] == "RED"
        os.chmod(path, 0o600)
        s.listen(1)
        assert r.judge_socket(path)["state"] == "OK"
        s.close()
        # A dead daemon leaves its 0600 socket behind; nobody answers it.
        assert r.judge_socket(path)["state"] == "RED", "a stale socket is not a serving daemon"
        path.unlink()
        path.write_text("x")
        assert r.judge_socket(path)["state"] == "RED"            # a file, not a socket


def test_the_reader_reads_the_ledger_or_says_unknown():
    r = _reader()
    with tempfile.TemporaryDirectory() as d:
        data = pathlib.Path(d)
        os.chmod(data, 0o700)
        db = data / "ledger.db"
        assert r.judge_ledger(db)[0]["state"] == "UNKNOWN"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, uuid TEXT, actor_id TEXT, status TEXT,"
                    " started_at TEXT, ended_at TEXT, stop_reason TEXT)")
        con.commit()
        lines = {x["check"]: x for x in r.judge_ledger(db)}
        assert lines["ledger"]["state"] == "OK" and "none yet" in lines["last session"]["detail"]
        con.execute("INSERT INTO sessions VALUES (1,'u1','user:abc','ended','2026-10-12T10:00:00Z',NULL,'end')")
        con.commit()
        con.close()
        assert "user:abc" in {x["check"]: x for x in r.judge_ledger(db)}["last session"]["detail"]
        os.chmod(data, 0o755)
        assert {x["check"]: x for x in r.judge_ledger(db)}["ledger"]["state"] == "RED"
        db.write_bytes(b"not a database")
        os.chmod(data, 0o700)
        assert r.judge_ledger(db)[0]["state"] == "UNKNOWN"


def test_the_reader_says_unknown_when_launchd_cannot_be_asked():
    r = _reader()
    assert r.judge_launchd(None)["state"] == "UNKNOWN"
    assert r.judge_launchd((113, ""))["state"] == "RED"
    assert r.judge_launchd((0, "state = running\n\tpid = 42\n"))["state"] == "OK"
    # Loaded but crash-looping on KeepAlive: no pid is a dead daemon, not a green one.
    assert r.judge_launchd((0, "state = not running\n\tlast exit code = 1\n"))["state"] == "RED"
