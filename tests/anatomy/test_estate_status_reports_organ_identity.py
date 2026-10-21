"""Anatomy gate: estate-status names what every host organ IS and who it runs as.

The medulla (ssot/doctrine/medulla.md, PROPOSED) will absorb the host organs one
by one and run them under one identity. Its measure is this axis: per self-owned
row with a launchd_label, the language, the runtime, the run-as user and uid, and
the launchd/systemd domain. A row with no deployed job is "not installed here"
(an absence, not a disagreement); a deployed job no process matches is UNREADABLE
"not reported", never ok.

Every case builds a fake root in tmp_path and hands fixture `ps` rows in — no
subprocess, no HTTP, no live path.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import plistlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "estate-status.py"
sys.path.insert(0, str(REPO / "tools"))
import nos_identity  # noqa: E402


def load():
    spec = importlib.util.spec_from_file_location("estate_status_identity", TOOL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # @dataclass looks itself up there
    spec.loader.exec_module(mod)
    assert hasattr(mod, "axis_identity"), "estate-status has no organ-identity axis"
    return mod


ORGANS = [r for r in nos_identity.services()
          if r.get("software_owner") == "self" and r.get("launchd_label")]
ME = os.getuid()
#: Fixture argv per organ: one of each runtime the summary counts.
ARGV = {
    "thalamus": ["/opt/nos/thalamus/bin/thalamus", "serve"],
    "wing": ["/opt/homebrew/bin/frankenphp", "php-server"],
    "cortex": ["/usr/local/bin/node", "/opt/nos/cortex/server.js"],
}


def argv(row: dict) -> list[str]:
    return ARGV.get(row["id"], ["/usr/bin/python3", f"/opt/nos/{row['id']}/main.py"])


def ps_row(uid: int, user: str, row: dict) -> str:
    return f"{uid} {user} {' '.join(argv(row))} --extra"


def lines(res, axis="identity"):
    return [x for x in res.lines if x.axis == axis]


def test_every_host_organ_reports_language_runtime_and_uid_on_macos(tmp_path):
    mod = load()
    assert len(ORGANS) >= 8, f"the manifest lost host organs: {[r['id'] for r in ORGANS]}"
    home = tmp_path / "home"
    agents, daemons = home / "Library/LaunchAgents", tmp_path / "Library/LaunchDaemons"
    agents.mkdir(parents=True)
    daemons.mkdir(parents=True)
    root_row, absent_row = ORGANS[0], ORGANS[-1]
    ps = []
    for row in ORGANS:
        if row is absent_row:
            continue
        label = row["launchd_label"]
        if row is root_row:
            (daemons / f"{label}.plist").write_bytes(plistlib.dumps(
                {"Label": label, "ProgramArguments": argv(row), "UserName": "root"}))
            ps.append(ps_row(0, "root", row))
        else:
            (agents / f"{label}.plist").write_bytes(plistlib.dumps(
                {"Label": label, "ProgramArguments": argv(row)}))
            ps.append(ps_row(ME, "pazny", row))
    res = mod.Result()
    mod.axis_identity(res, root=tmp_path, home=home, ps_lines=ps)
    got = lines(res)
    for row in ORGANS:
        mine = [x for x in got if x.subject == row["id"]]
        assert len(mine) == 1, f"{row['id']}: expected one identity line, got {mine}"
        line = mine[0]
        if row is absent_row:
            assert "not installed here" in line.detail and line.state == mod.OK, line
            continue
        assert line.state == mod.OK, line
        assert row["id"] in line.detail
        if row is root_row:
            assert "runs as root uid 0" in line.detail and "LaunchDaemon" in line.detail, line
        else:
            assert f"runs as pazny uid {ME}" in line.detail and "LaunchAgent" in line.detail, line
    by = {x.subject: x.detail for x in got}
    if "thalamus" in by and absent_row["id"] != "thalamus":
        assert "rust/native" in by["thalamus"], by["thalamus"]
    if "wing" in by and absent_row["id"] != "wing":
        assert "php/php" in by["wing"], by["wing"]
    summary = [x for x in got if x.subject == "summary"]
    assert len(summary) == 1, got
    s = summary[0].detail
    assert s.startswith("host runtimes:") and "· run as operator" in s, s
    n = len(ORGANS) - 1
    assert f"operator {n - 1}, root 1, other 0" in s, s


def test_every_host_organ_reports_language_runtime_and_uid_on_linux(tmp_path):
    mod = load()
    home = tmp_path / "home"
    user, system = home / ".config/systemd/user", tmp_path / "etc/systemd/system"
    user.mkdir(parents=True)
    system.mkdir(parents=True)
    sys_row = ORGANS[1]
    ps = []
    for row in ORGANS:
        label = row["launchd_label"]
        exec_start = "ExecStart=" + " ".join(argv(row))
        if row is sys_row:
            (system / f"{label}.service").write_text(f"[Service]\nUser=nos\n{exec_start}\n")
            ps.append(ps_row(990, "nos", row))
        else:
            (user / f"{label}.service").write_text(f"[Unit]\nDescription=x\n[Service]\n{exec_start}\n")
            ps.append(ps_row(ME, "pazny", row))
    res = mod.Result()
    mod.axis_identity(res, root=tmp_path, home=home, ps_lines=ps)
    got = {x.subject: x for x in lines(res)}
    for row in ORGANS:
        line = got[row["id"]]
        assert line.state == mod.OK, line
        if row is sys_row:
            assert "runs as nos uid 990" in line.detail and "system unit" in line.detail, line
        else:
            assert f"runs as pazny uid {ME}" in line.detail and "user unit" in line.detail, line
    assert f"operator {len(ORGANS) - 1}, root 0, other 1" in got["summary"].detail, got["summary"]
    assert "rust/native" in got["thalamus"].detail and "node/node" in got["cortex"].detail


def test_a_declared_daemon_ps_cannot_see_is_not_reported_never_ok(tmp_path):
    mod = load()
    home = tmp_path / "home"
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    row = ORGANS[0]
    (agents / f"{row['launchd_label']}.plist").write_bytes(plistlib.dumps(
        {"Label": row["launchd_label"], "ProgramArguments": argv(row)}))
    res = mod.Result()
    mod.axis_identity(res, root=tmp_path, home=home, ps_lines=["1 someone /bin/unrelated"])
    line = next(x for x in lines(res) if x.subject == row["id"])
    assert line.state == mod.UNREADABLE and "not reported" in line.detail, line
    # and ps itself failing is unreadable too, not a silent pass
    res = mod.Result()
    mod.axis_identity(res, root=tmp_path, home=home, ps_lines=[])
    line = next(x for x in lines(res) if x.subject == row["id"])
    assert line.state == mod.UNREADABLE, line


def test_the_default_run_includes_the_identity_axis(monkeypatch):
    mod = load()
    called = []
    for name in ("axis_repos", "axis_organs", "axis_blank", "axis_toolchain", "axis_identity"):
        monkeypatch.setattr(mod, name, lambda *a, _n=name, **k: called.append(_n))
    monkeypatch.setattr(sys, "argv", ["estate-status.py", "--no-fetch", "--json"])
    mod.main()
    assert "axis_identity" in called, f"the default run skipped the identity axis: {called}"
    assert called.index("axis_identity") > called.index("axis_organs"), called


def test_a_python_shim_and_a_venv_entry_script_are_still_seen(tmp_path):
    """Measured live 2026-10-21: /usr/bin/python3 re-execs as the framework Python, so
    ps never starts with argv0; a venv `uvicorn` is a python script, not native."""
    mod = load()
    home = tmp_path / "home"
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    shim_row, venv_row = ORGANS[0], ORGANS[1]
    script = tmp_path / "venv/bin/uvicorn"
    script.parent.mkdir(parents=True)
    script.write_text("#!/opt/venv/bin/python3\nimport uvicorn\n")
    for row, args in ((shim_row, ["/usr/bin/python3", "/opt/nos/gw.py"]),
                      (venv_row, [str(script), "main:app"])):
        (agents / f"{row['launchd_label']}.plist").write_bytes(plistlib.dumps(
            {"Label": row["launchd_label"], "ProgramArguments": args}))
    ps = [f"{ME} pazny /Library/Frameworks/Python3.framework/MacOS/Python /opt/nos/gw.py",
          f"{ME} pazny /opt/venv/bin/python3 {script} main:app"]
    res = mod.Result()
    mod.axis_identity(res, root=tmp_path, home=home, ps_lines=ps)
    got = {x.subject: x for x in lines(res)}
    for row in (shim_row, venv_row):
        assert got[row["id"]].state == mod.OK, got[row["id"]]
        assert "python/python" in got[row["id"]].detail, got[row["id"]]


def test_a_scheduled_job_between_runs_is_idle_not_unreadable(tmp_path):
    """backup.rustfs fires on a calendar and exits; between runs ps has nothing to match.
    That is a known state, not an unreadable side, so it must not turn the default run red."""
    mod = load()
    home = tmp_path / "home"
    agents, units = home / "Library/LaunchAgents", home / ".config/systemd/user"
    agents.mkdir(parents=True)
    units.mkdir(parents=True)
    mac_row, linux_row, daemon_row = ORGANS[0], ORGANS[1], ORGANS[2]
    (agents / f"{mac_row['launchd_label']}.plist").write_bytes(plistlib.dumps(
        {"Label": mac_row["launchd_label"], "ProgramArguments": argv(mac_row),
         "StartCalendarInterval": {"Hour": 3, "Minute": 0}}))
    (units / f"{linux_row['launchd_label']}.service").write_text(
        "[Service]\nType=oneshot\nExecStart=" + " ".join(argv(linux_row)) + "\n")
    (units / f"{linux_row['launchd_label']}.timer").write_text("[Timer]\nOnCalendar=daily\n")
    (agents / f"{daemon_row['launchd_label']}.plist").write_bytes(plistlib.dumps(
        {"Label": daemon_row["launchd_label"], "ProgramArguments": argv(daemon_row)}))
    res = mod.Result()
    mod.axis_identity(res, root=tmp_path, home=home, ps_lines=["1 someone /bin/unrelated"])
    got = {x.subject: x for x in lines(res)}
    for row in (mac_row, linux_row):
        assert got[row["id"]].state == mod.OK, got[row["id"]]
        assert "scheduled, idle" in got[row["id"]].detail, got[row["id"]]
    # a daemon that should be resident and is not stays unreadable
    assert got[daemon_row["id"]].state == mod.UNREADABLE, got[daemon_row["id"]]
