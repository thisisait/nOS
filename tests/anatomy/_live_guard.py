"""The offline boundary of tests/anatomy — enforced, not assumed.

2026-09-20: an "offline" pytest run auto-discovered RustFS credentials via
`docker inspect` and wrote 7 objects into the production raw-archive bucket,
Object-Lock COMPLIANCE for 3650 days. Nothing on the host said no: a test here
could read ~/.nos/secrets.yml, run docker, inherit the operator's tokens and
connect to any loopback service port exactly like a converge can.

Four doors, closed at conftest import for every test AND every subprocess it
spawns (HOME and PATH are inherited; the socket patch is in-process only):

  ~/.nos            HOME becomes a symlink farm of the real home MINUS .nos
                    (an empty .nos stands in, so writers land in the sandbox)
  docker            a PATH shim refuses with exit 125 and says why
  secret env vars   *_TOKEN / *_SECRET / *_PASSWORD / AWS_* are scrubbed
  loopback ports    socket.connect to 127.0.0.1 / ::1 below the ephemeral
                    floor raises; a test's own server (port 0) still works

Opt in per test with `@pytest.mark.live`; disarm a whole run with NOS_LIVE=1
(the e2e suites live under tests/e2e and never load this). Gate:
tests/anatomy/test_a_test_cannot_reach_the_live_estate.py.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import pathlib
import re
import shutil
import socket
import tempfile

ENV = "NOS_LIVE"
MARK = "live"
EPHEMERAL_FLOOR = 32768                       # Linux default floor; macOS starts at 49152
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
SECRET_ENV = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|APIKEY)$|^AWS_", re.I)
REFUSAL = ("refused by tests/anatomy/_live_guard.py — tests/anatomy is offline; "
           "mark the test @pytest.mark.live or run with NOS_LIVE=1")

_real: dict = {}
_armed = False


def live_run() -> bool:
    return os.environ.get(ENV, "").strip().lower() in ("1", "true", "yes")


#: Credential holders under HOME: the secret store, and the launchd / systemd
#: unit files whose env blocks carry the organs' tokens (test_hub_url_audit.py
#: read WING_API_TOKEN out of the wing plist). Each becomes an empty directory.
HIDDEN = (".nos", "Library/LaunchAgents", ".config/systemd/user")


def _farm(real: pathlib.Path, fake: pathlib.Path, hidden: tuple[str, ...]) -> None:
    for entry in real.iterdir():
        below = tuple(h.split("/", 1)[1] for h in hidden if h.startswith(entry.name + "/"))
        if entry.name in hidden or below:
            (fake / entry.name).mkdir()
            if below:
                _farm(entry, fake / entry.name, below)
        else:
            (fake / entry.name).symlink_to(entry)
    for h in hidden:
        if "/" not in h:
            (fake / h).mkdir(exist_ok=True)


def _fake_home(real: pathlib.Path) -> pathlib.Path:
    home = pathlib.Path(tempfile.mkdtemp(prefix="nos-pytest-home-"))
    atexit.register(shutil.rmtree, home, True)
    _farm(real, home, HIDDEN)
    return home


def _docker_shim() -> pathlib.Path:
    d = pathlib.Path(tempfile.mkdtemp(prefix="nos-pytest-bin-"))
    atexit.register(shutil.rmtree, d, True)
    for name in ("docker", "docker-compose"):
        p = d / name
        p.write_text(f"#!/bin/sh\necho '{name}: {REFUSAL}' >&2\nexit 125\n")
        p.chmod(0o755)
    return d


def _refused(address) -> str | None:
    if isinstance(address, tuple) and len(address) >= 2:
        host, port = address[0], address[1]
        if host in LOOPBACK and isinstance(port, int) and port < EPHEMERAL_FLOOR:
            return f"connect to {host}:{port} {REFUSAL}"
    return None


def _connect(self, address):
    why = _refused(address)
    if why:
        raise ConnectionRefusedError(why)
    return _real["connect"](self, address)


def _connect_ex(self, address):
    why = _refused(address)
    if why:
        raise ConnectionRefusedError(why)
    return _real["connect_ex"](self, address)


def arm() -> None:
    global _armed
    if _armed or live_run():
        return
    real_home = pathlib.Path(os.environ.get("HOME") or pathlib.Path.home())
    _real.update(
        HOME=str(real_home),
        PATH=os.environ.get("PATH", ""),
        scrubbed={k: os.environ.pop(k) for k in list(os.environ) if SECRET_ENV.search(k)},
        connect=socket.socket.connect,
        connect_ex=socket.socket.connect_ex,
    )
    os.environ["HOME"] = str(_fake_home(real_home))
    os.environ["PATH"] = f"{_docker_shim()}{os.pathsep}{_real['PATH']}"
    socket.socket.connect = _connect
    socket.socket.connect_ex = _connect_ex
    _armed = True


@contextlib.contextmanager
def lifted():
    """The boundary, lifted for one `@pytest.mark.live` test and restored after."""
    if not _armed:
        yield
        return
    fake_home, fake_path = os.environ["HOME"], os.environ["PATH"]
    os.environ["HOME"], os.environ["PATH"] = _real["HOME"], _real["PATH"]
    os.environ.update(_real["scrubbed"])
    socket.socket.connect, socket.socket.connect_ex = _real["connect"], _real["connect_ex"]
    try:
        yield
    finally:
        for k in _real["scrubbed"]:
            os.environ.pop(k, None)
        os.environ["HOME"], os.environ["PATH"] = fake_home, fake_path
        socket.socket.connect, socket.socket.connect_ex = _connect, _connect_ex
