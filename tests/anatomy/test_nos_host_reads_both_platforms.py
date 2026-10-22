"""tools/nos_host.py answers the same questions on launchd and systemd --user.

Fixtures are the hosts' own output: the Linux ones captured on the DGX Spark
(aarch64, Ubuntu 24.04, `ss` as the operator) 2026-10-22, the Darwin ones in
the shape the readers parsed before the shim existed. Each probe is driven
through `run=` with the platform pinned, so both halves run on either host.

The rule under test is the reader contract: a source that cannot be read is
None (UNKNOWN), never an empty answer that reads as "nothing there".
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_host as h  # noqa: E402

# ── Linux fixtures (spark1, 2026-10-22) ──────────────────────────────────────

SS_LTNP = """\
LISTEN 0      4096       127.0.0.1:631   0.0.0.0:*
LISTEN 0      4096       127.0.0.1:3004  0.0.0.0:*
LISTEN 0      4096      172.17.0.1:11434 0.0.0.0:*
LISTEN 0      511        127.0.0.1:8098  0.0.0.0:* users:(("MainThread",pid=1577822,fd=30))
LISTEN 0      4096      172.17.0.1:9000  0.0.0.0:* users:(("frankenphp",pid=3833954,fd=9))
LISTEN 0      4096   127.0.0.53%lo:53    0.0.0.0:*
LISTEN 0      4096       127.0.0.1:11434 0.0.0.0:*
LISTEN 0      4096         0.0.0.0:22    0.0.0.0:*
LISTEN 0      4096         0.0.0.0:443   0.0.0.0:*
LISTEN 0      4096            [::]:22       [::]:*
LISTEN 0      4096            [::]:443      [::]:*
"""
LIST_SOCKETS = """\
0.0.0.0:22                             ssh.socket                      ssh.service
127.0.0.1:11434                        nos-ollama-loopback.socket      nos-ollama-loopback.service
@/org/kernel/linux/storage/multipathd  multipathd.socket               multipathd.service
[::]:22                                ssh.socket                      ssh.service
audit 1                                systemd-journald-audit.socket   systemd-journald.service
"""
DOCKER_PS = """\
127.0.0.1:8091->8080/tcp
127.0.0.1:3004->8080/tcp

0.0.0.0:80->80/tcp, [::]:80->80/tcp, 0.0.0.0:443->443/tcp, [::]:443->443/tcp, 127.0.0.1:8082->8080/tcp
2375/tcp
"""
SHOW_TWO = """\
MainPID=2642
Id=eu.thisisait.nos.pulse.service
LoadState=loaded
ActiveState=active
SubState=running

MainPID=0
Id=eu.thisisait.nos.nope.service
LoadState=not-found
ActiveState=inactive
SubState=dead
"""
LIST_UNITS = """\
dbus.service                       loaded    active   running D-Bus User Message Bus
docker.service                     loaded    inactive dead    Docker Application Container Engine (Rootless)
eu.thisisait.nos.pulse.service     loaded    active   running nOS Pulse — scheduled-job daemon
ghost.service                      not-found inactive dead    ghost.service
"""
SHOW_LOADED = """\
Id=dbus.service
MainPID=2400

Id=docker.service
MainPID=0

Id=eu.thisisait.nos.pulse.service
MainPID=2642
"""
UNIT = """\
[Unit]
Description=nOS thalamus — Iris for every login (shared socket, peer-named)
ExecStart=/not/this

[Service]
Type=simple
EnvironmentFile=-{envfile}
Environment="NOS_TIER=2" PLAIN=x
ExecStart=/home/u/thalamus/bin/thalamus serve --data-dir "/home/u/nos/thalamus data"
Restart=always
"""
ENVFILE = """\
# rendered by the role
THALAMUS_SOCKET=/run/nos/thalamus.sock
THALAMUS_SOCKET_SHARED=1
THALAMUS_RELAY_SECRET='fixture-not-a-secret'
"""

# ── Darwin fixtures ──────────────────────────────────────────────────────────

LAUNCHCTL_RUNNING = """\
gui/501/eu.thisisait.nos.wing = {
\tactive count = 1
\tstate = running
\tenvironment = {
\t\tNOS_MINIMAX_MODEL => MiniMax-M2.7
\t\tWING_API_TOKEN => fixture
\t}
\tpid = 4242
\tlast exit code = (never exited)
}
"""
LAUNCHCTL_DEAD = "gui/501/x = {\n\tstate = not running\n\tlast exit code = 1\n}\n"
LAUNCHCTL_LIST = "PID\tStatus\tLabel\n500\t0\teu.thisisait.nos.bone\n-\t0\teu.thisisait.nos.backup\n"
NETSTAT = """\
tcp4  0 0  *.4444          *.*  LISTEN  0 0 131072 131072  com.docker.backend:50  00100 00000106 0 0 00000800 1 0 000000
tcp46 0 0  *.18080         *.*  LISTEN  0 0 131072 131072             node:60  00100 00000106 0 0 00000800 1 0 000000
tcp4  0 0  127.0.0.1.5173  *.*  LISTEN  0 0 131072 131072             node:61  00100 00000106 0 0 00000800 1 0 000000
"""
PS = "50 1 /Applications/Docker.app/Contents/MacOS/com.docker.backend\n60 1 node\n61 1 node\n"


def fake(table: dict[str, tuple[int, str] | None]):
    """argv -> canned (rc, stdout), keyed by the argv's first two words."""
    calls = []

    def run(argv):
        calls.append(argv)
        for key, val in table.items():
            if " ".join(argv).startswith(key):
                return val
        return None
    run.calls = calls
    return run


# ── service state ────────────────────────────────────────────────────────────

def test_a_running_systemd_unit_reads_like_a_running_launchd_job():
    run = fake({"systemctl --user show": (0, SHOW_TWO.split("\n\n")[0] + "\n")})
    st = h.service_state("eu.thisisait.nos.pulse", run=run, system="Linux")
    assert (st["loaded"], st["running"], st["pid"]) == (True, True, 2642)
    assert run.calls[0][:4] == ["systemctl", "--user", "show", "eu.thisisait.nos.pulse.service"]
    mac = h.service_state("x", run=fake({"launchctl print": (0, LAUNCHCTL_RUNNING)}), system="Darwin")
    assert (mac["loaded"], mac["running"], mac["pid"]) == (True, True, 4242)


def test_not_loaded_and_not_running_are_different_answers():
    gone = h.service_state("x", run=fake({"systemctl": (0, SHOW_TWO.split("\n\n")[1])}), system="Linux")
    assert (gone["loaded"], gone["running"]) == (False, False)
    dead = h.state_from_systemd({"LoadState": "loaded", "ActiveState": "failed", "SubState": "failed", "MainPID": "0"})
    assert (dead["loaded"], dead["running"]) == (True, False) and "failed" in dead["detail"]
    assert h.parse_launchctl_print(113, "")["loaded"] is False
    mac = h.parse_launchctl_print(0, LAUNCHCTL_DEAD)
    assert (mac["loaded"], mac["running"]) == (True, False) and "last exit 1" in mac["detail"]


def test_an_unreachable_service_manager_is_unknown_not_stopped():
    assert h.service_state("x", run=fake({}), system="Linux") is None          # no systemctl
    assert h.service_state("x", run=fake({"systemctl": (1, "Failed to connect to bus")}), system="Linux") is None
    assert h.service_state("x", run=fake({}), system="Darwin") is None         # no launchctl
    assert h.service_state("x", run=fake({}), system="Windows") is None
    assert h.loaded_services(run=fake({}), system="Linux") is None
    assert h.listeners(run=fake({}), system="Linux") is None
    assert h.listeners(run=fake({}), system="Darwin") is None


def test_loaded_services_keeps_only_loaded_units_with_their_pids():
    run = fake({"systemctl --user list-units": (0, LIST_UNITS), "systemctl --user show": (0, SHOW_LOADED)})
    got = h.loaded_services(run=run, system="Linux")
    assert got == {"dbus": 2400, "docker": None, "eu.thisisait.nos.pulse": 2642}
    assert "ghost.service" not in run.calls[1], "a not-found unit is not loaded"
    mac = h.loaded_services(run=fake({"launchctl list": (0, LAUNCHCTL_LIST)}), system="Darwin")
    assert mac == {"eu.thisisait.nos.bone": 500, "eu.thisisait.nos.backup": None}


# ── listeners ────────────────────────────────────────────────────────────────

def test_linux_listeners_name_the_owner_or_say_it_is_not_visible():
    run = fake({"ss -ltnpH": (0, SS_LTNP), "systemctl list-sockets": (0, LIST_SOCKETS),
                "docker ps": (0, DOCKER_PS)})
    rows = {(r["addr"], r["port"]): r for r in h.listeners(run=run, system="Linux")}
    assert rows[("172.17.0.1", 9000)]["pid"] == 3833954, "our own process: ss names it"
    assert rows[("0.0.0.0", 22)]["exe"] == h.SYSTEMD_EXE and rows[("::", 22)]["unit"] == "ssh.socket"
    assert rows[("127.0.0.1", 11434)]["unit"] == "nos-ollama-loopback.socket"
    assert rows[("0.0.0.0", 443)]["exe"] == "docker-proxy" and rows[("::", 443)]["exe"] == "docker-proxy"
    assert rows[("127.0.0.1", 3004)]["exe"] == "docker-proxy"
    hidden = rows[("172.17.0.1", 11434)]
    assert (hidden["exe"], hidden["pid"]) == (h.OWNER_HIDDEN, None), "not ours to see: said, not guessed"
    assert ("127.0.0.53", 53) in rows, "an interface-scoped address parses"


def test_linux_listeners_survive_without_docker_or_list_sockets():
    rows = h.listeners(run=fake({"ss -ltnpH": (0, SS_LTNP)}), system="Linux")
    assert len(rows) == 11 and {r["exe"] for r in rows if r["pid"] is None} == {h.OWNER_HIDDEN}


def test_darwin_listeners_parse_netstat_and_ps():
    run = fake({"netstat": (0, NETSTAT), "ps": (0, PS)})
    rows = h.listeners(run=run, system="Darwin")
    assert [(r["port"], r["pid"], r["exe"].rsplit("/", 1)[-1]) for r in rows] == [
        (4444, 50, "com.docker.backend"), (18080, 60, "node"), (5173, 61, "node")]
    assert rows[1]["addr"] == "*" and rows[2]["addr"] == "127.0.0.1"


def test_docker_ports_cover_every_published_address_and_ranges():
    assert h.parse_docker_ports(DOCKER_PS) == {8091, 3004, 80, 443, 8082}
    assert h.parse_docker_ports("0.0.0.0:7010-7011->7010-7011/tcp") == {7010, 7011}
    assert h.parse_docker_ports("0.0.0.0:53->53/udp") == set(), "a UDP port is not a TCP listener"


# ── definition, environment, log ─────────────────────────────────────────────

def test_a_unit_file_gives_argv_and_env_like_a_plist(tmp_path, monkeypatch):
    env = tmp_path / "thalamus.env"
    env.write_text(ENVFILE)
    unit_dir = tmp_path / ".config/systemd/user"
    unit_dir.mkdir(parents=True)
    (unit_dir / "eu.thisisait.nos.thalamus.service").write_text(UNIT.format(envfile=env))
    monkeypatch.setattr(h, "HOME", tmp_path)
    d = h.service_definition("eu.thisisait.nos.thalamus", system="Linux")
    assert d["argv"] == ["/home/u/thalamus/bin/thalamus", "serve", "--data-dir", "/home/u/nos/thalamus data"]
    assert d["env"]["THALAMUS_SOCKET"] == "/run/nos/thalamus.sock"
    assert d["env"]["NOS_TIER"] == "2" and d["env"]["PLAIN"] == "x"
    assert d["env"]["THALAMUS_RELAY_SECRET"] == "fixture-not-a-secret", "quotes stripped"
    assert h.service_definition("eu.thisisait.nos.absent", system="Linux") is None


def test_unit_files_skip_aliases_and_masks(tmp_path, monkeypatch):
    d = tmp_path / "user"
    d.mkdir()
    (d / "eu.thisisait.nos.backup.service").write_text("[Service]\nExecStart=/usr/bin/restic backup\n")
    (d / "eu.thisisait.nos.backup.timer").write_text("[Timer]\nOnCalendar=daily\n")
    (d / "masked.service").symlink_to("/dev/null")
    monkeypatch.setattr(h, "UNIT_DIRS", (d,))
    assert h.unit_files(system="Linux") == {
        "eu.thisisait.nos.backup": {"path": str(d / "eu.thisisait.nos.backup.service"), "program": "/usr/bin/restic"}}


def test_the_running_env_is_read_from_the_job_not_the_file():
    run = fake({"launchctl print": (0, LAUNCHCTL_RUNNING)})
    assert h.service_env("eu.thisisait.nos.wing", run=run, system="Darwin")["NOS_MINIMAX_MODEL"] == "MiniMax-M2.7"
    assert h.service_env("x", run=fake({"launchctl": (113, "")}), system="Darwin") is None
    # Linux: a unit with no main process has no environment to read.
    stopped = fake({"systemctl": (0, SHOW_TWO.split("\n\n")[1])})
    assert h.service_env("eu.thisisait.nos.nope", run=stopped, system="Linux") is None


def test_the_journal_is_the_linux_stderr_log():
    run = fake({"journalctl": (0, "thalamus: model bound x\nthalamus: relay closed\n")})
    lines, src = h.service_log("eu.thisisait.nos.thalamus", grep="thalamus: ", run=run, system="Linux")
    assert lines[-1] == "thalamus: relay closed" and src.startswith("journalctl --user -u eu.thisisait.nos.thalamus")
    assert "--grep" in run.calls[0]
    assert h.service_log("x", grep="y", run=fake({"journalctl": (1, "")}), system="Linux") == ([], src.replace(
        "eu.thisisait.nos.thalamus", "x")), "no match is an empty answer"
    assert h.service_log("x", run=fake({}), system="Linux") is None


# ── macOS-only sources say so off the Mac ────────────────────────────────────

def test_macos_only_sources_are_none_elsewhere():
    assert h.unified_log(["show"], system="Linux") is None
    assert h.lsof("-nP", system="Linux") is None
    assert h.lsof("-nP", run=fake({"lsof": (1, "")}), system="Darwin") == "", "rc 1 = nothing matched"
    assert h.sockets("openhuman", system="Darwin") is None
