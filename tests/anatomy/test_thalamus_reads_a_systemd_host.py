"""tools/thalamus-status.py on Linux: the same six lines, from systemd.

On the DGX Spark every line but the socket was UNKNOWN (launchctl, a plist and
a launchd log that do not exist there) and the socket line was RED: it looked
for ~/.nos/thalamus.sock at 0600 while the Linux role serves a SHARED socket
(/run/nos/thalamus.sock, THALAMUS_SOCKET_SHARED=1 -> 0666 by design, src/main.rs).
These pin the Linux half: path and mode from the unit's env, the job from
systemctl, the start lines from the journal, the ledger from ExecStart.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import socket
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
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
        try:
            os.chmod(path, 0o666)
            assert r.judge_socket(path, 0o666)["state"] == "OK"
            assert r.judge_socket(path)["state"] == "RED", "a private socket at 0666 is open to every login"
            os.chmod(path, 0o600)
            assert r.judge_socket(path)["state"] == "OK"
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


def test_an_unreadable_journal_or_unit_is_unknown(monkeypatch):
    r = _reader()
    monkeypatch.setattr(r.nos_host, "SYSTEM", "Linux")
    monkeypatch.delenv("NOS_THALAMUS_LEDGER", raising=False)
    monkeypatch.setattr(r.nos_host, "service_definition", lambda label: None)
    monkeypatch.setattr(r.nos_host, "service_state", lambda label: None)
    monkeypatch.setattr(r.nos_host, "service_log", lambda label, **k: None)
    rows = {x["check"]: x for x in r.collect()}
    for check in ("socket", "systemd", "model", "relay", "ledger", "last session"):
        assert rows[check]["state"] == "UNKNOWN", (check, rows[check])
