"""tools/undeclared-status.py on a systemd host: the same three axes, read.

Before tools/nos_host.py the launchd and ports axes were UNKNOWN on Linux for
good (`launchctl` and Darwin `netstat` do not exist there), so red-status
carried two permanent UNKNOWN lines on the DGX Spark. These pin what the
Linux half says instead: the declared set is still DERIVED (a role template
named for its unit is the systemd twin of a literal plist Label), snapd's own
units are the OS, and a listener whose owner `ss` cannot show is named as
such — never guessed, never dropped.
"""

from __future__ import annotations

import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "undeclared-status.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_role_template_named_for_its_unit_declares_it():
    labels = _load("_ul_a").declared_labels()
    assert {"ollama", "nos-ollama-loopback", "nos-jupyterhub", "nos-jupyterhub-proxy"} <= labels
    assert "service" not in labels, "pazny.linux.systemd_user's generic service.j2 names no unit"


def test_linux_collect_names_strangers_and_spares_the_os(monkeypatch):
    mod = _load("_ul_b")
    monkeypatch.setattr(mod, "SYSTEM", "Linux")
    monkeypatch.setattr(mod, "declared_labels", lambda: {"eu.thisisait.nos.bone", "ollama"})
    monkeypatch.setattr(mod, "declared_ports", lambda: {443})
    monkeypatch.setattr(mod, "declared_programs", lambda: frozenset())
    monkeypatch.setattr(mod, "habitat", lambda: frozenset())
    monkeypatch.setattr(mod, "crontab", lambda: [])
    monkeypatch.setattr(mod, "loaded_labels", lambda: {"eu.thisisait.nos.bone": 500, "docker": None,
                                                        "snap.x.y": 7})
    monkeypatch.setattr(mod, "plist_files", lambda: {
        "eu.thisisait.nos.bone": {"path": "/h/.config/systemd/user/eu.thisisait.nos.bone.service", "program": "/b"},
        "docker": {"path": "/h/.config/systemd/user/docker.service", "program": "/usr/bin/dockerd-rootless.sh"},
        "snap.x.y": {"path": "/etc/systemd/user/snap.x.y.service", "program": "/usr/bin/snap", "generator": "snapd"},
        "ollama": {"path": "/etc/systemd/system/ollama.service", "program": "/usr/local/bin/ollama"},
        "vendor-agent": {"path": "/etc/systemd/system/vendor-agent.service", "program": "/opt/v"}})
    monkeypatch.setattr(mod, "listeners", lambda: [
        {"addr": "0.0.0.0", "port": 22, "pid": 1, "ppid": 0, "exe": "/usr/lib/systemd/systemd", "unit": "ssh.socket"},
        {"addr": "0.0.0.0", "port": 443, "pid": None, "ppid": None, "exe": "docker-proxy"},
        {"addr": "0.0.0.0", "port": 4444, "pid": None, "ppid": None, "exe": "docker-proxy"},
        {"addr": "127.0.0.1", "port": 631, "pid": None, "ppid": None, "exe": "?"},
        {"addr": "172.17.0.1", "port": 8010, "pid": None, "ppid": None, "exe": "?"}])
    report = mod.collect()
    assert report["sources_missing"] == []
    rows = {d["label"]: d for d in report["launchd"]}
    assert set(rows) == {"docker", "vendor-agent"}, "snapd's unit is the OS; ollama is declared"
    assert rows["vendor-agent"]["loaded"] is None, "the system domain is not asked by --user"
    assert [p["port"] for p in report["ports"]] == [4444, 8010], \
        "ssh.socket is the OS, 443 declared, a loopback stranger is not judged"
    said = mod.summary(report)
    assert "port 172.17.0.1:8010 (owner not visible to this user)" in said
    assert "port 0.0.0.0:4444 (docker-proxy)" in said


def test_an_unreadable_linux_axis_names_the_linux_command(monkeypatch):
    mod = _load("_ul_c")
    monkeypatch.setattr(mod, "SYSTEM", "Linux")
    monkeypatch.setattr(mod, "loaded_labels", lambda: None)
    monkeypatch.setattr(mod, "listeners", lambda: None)
    monkeypatch.setattr(mod, "crontab", lambda: [])
    missing = mod.collect()["sources_missing"]
    assert any(m.startswith("systemd --user (systemctl --user") for m in missing), missing
    assert any("ss -ltnp" in m for m in missing), missing
    assert not any("launchctl" in m or "netstat" in m for m in missing), "a Linux host is not told about launchctl"
