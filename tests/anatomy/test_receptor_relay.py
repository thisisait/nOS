"""The receptor: a host login reaches KEAP's human door as the person it maps to.

2026-10-11 (operator rulings 1a, 2): on the Mac the person behind a host login
comes from ~/.nos/identity-map.yml (host login -> {username, groups}); the
kernel names the login (SO_PEERCRED on Linux, LOCAL_PEERCRED on macOS), never a
header. An unmapped login is refused, never defaulted. Client X-Authentik-* and
x-keap-proxy-secret are dropped; the receptor injects its own. The socket is 0600.

Offline: the receptor runs as a subprocess in front of a recording HTTP server.
"""
from __future__ import annotations

import http.server
import importlib.util
import json
import os
import pathlib
import pwd
import socket
import subprocess
import sys
import tempfile
import threading
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
RELAY = REPO / "files" / "anatomy" / "receptor" / "receptor.py"
ME = pwd.getpwuid(os.getuid()).pw_name
HAS_PEERCRED = hasattr(socket, "SO_PEERCRED") or hasattr(socket, "LOCAL_PEERCRED")
needs_peercred = pytest.mark.skipif(not HAS_PEERCRED, reason="no SO_PEERCRED / LOCAL_PEERCRED on this platform")


def _relay():
    spec = importlib.util.spec_from_file_location("receptor", RELAY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@needs_peercred
def test_the_kernel_names_the_peer_on_this_platform():
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        assert _relay().peer_uid(a) == os.getuid()
    finally:
        a.close()
        b.close()


def _upstream(seen: list):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(dict(self.headers))
            body = b'{"success":true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_POST = do_PUT = do_PATCH = do_DELETE = do_GET

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _run(logins: dict, extra: str = "", secret: str = "s3cret", raw: bytes | None = None):
    d = pathlib.Path(tempfile.mkdtemp(prefix="rcp-", dir="/tmp"))
    sock, mapf = d / "s", d / "identity-map.yml"
    mapf.write_text(json.dumps({"logins": logins}))
    seen: list = []
    up = _upstream(seen)
    proc = subprocess.Popen([sys.executable, str(RELAY), "--socket", str(sock), "--map", str(mapf),
                             "--upstream", f"127.0.0.1:{up.server_port}"],
                            env={**os.environ, "KEAP_PROXY_SHARED_SECRET": secret},
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(100):
            if sock.exists():
                break
            time.sleep(0.05)
        mode = sock.stat().st_mode & 0o777
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(15)  # a relay that waits on a body it was promised must fail, not hang
        c.connect(str(sock))
        c.sendall(raw or ("GET /api/tables HTTP/1.1\r\nHost: keap\r\n" + extra + "Connection: close\r\n\r\n").encode())
        reply = b""
        try:
            while chunk := c.recv(65536):
                reply += chunk
        except socket.timeout:
            reply = b"HTTP/1.1 TIMEOUT"
        c.close()
        return mode, reply.split(b" ", 2)[1].decode(), seen
    finally:
        proc.terminate()
        proc.wait(5)
        up.shutdown()


@needs_peercred
def test_a_mapped_login_reaches_keap_as_its_person_and_forgeries_are_dropped():
    forged = "X-Authentik-Username: akadmin\r\nX-Authentik-Groups: nos-admins\r\nx-keap-proxy-secret: guess\r\n"
    mode, status, seen = _run({ME: {"username": "alice", "groups": ["nos-users"]}}, forged)
    assert mode == 0o600, oct(mode)
    assert status == "200" and len(seen) == 1, (status, seen)
    h = {k.lower(): v for k, v in seen[0].items()}
    assert (h["x-authentik-username"], h["x-authentik-groups"], h["x-keap-proxy-secret"]) == (
        "alice", "nos-users", "s3cret"), h
    assert list(seen[0]).count("X-Authentik-Username") == 1, "a forged identity header survived"


@needs_peercred
def test_an_unmapped_login_is_refused_and_keap_never_hears_it():
    _, status, seen = _run({"someone-else": {"username": "bob", "groups": ["nos-users"]}})
    assert (status, seen) == ("403", [])


@needs_peercred
def test_without_the_proxy_secret_it_refuses_rather_than_sends_a_bare_identity():
    _, status, seen = _run({ME: {"username": "alice", "groups": ["nos-users"]}}, secret="")
    assert (status, seen) == ("503", [])


def test_the_default_map_is_derived_from_the_roster():
    """No nos_identity_map: the operator's login is nos_primary_admin, each
    extra identity a login of its own name, groups from its tier."""
    import jinja2
    tpl = (REPO / "roles/pazny.receptor/templates/identity-map.yml.j2").read_text()
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["to_nice_json"] = lambda v: json.dumps(v, indent=4, sort_keys=True)
    tiers = [{"tier": 1, "groups": ["nos-providers", "nos-admins"]},
             {"tier": 3, "groups": ["nos-providers", "nos-admins", "nos-managers", "nos-users"]}]
    ctx = {"ansible_facts": {"user_id": "pazny"}, "nos_primary_admin": "pazny", "authentik_rbac_tiers": tiers,
           "nos_identities": [{"name": "pazny", "tier": 1}], "nos_identity_map": {},
           "nos_extra_identities": [{"name": "iris", "email": "i@x", "tier": 3}]}
    got = json.loads(env.from_string(tpl).render(**ctx))
    assert got == {"logins": {"pazny": {"username": "pazny", "groups": ["nos-providers", "nos-admins"]},
                              "iris": {"username": "iris", "groups": ["nos-users"]}}}, got
    over = {"studio": {"username": "pazny", "groups": ["nos-admins"]}}
    assert json.loads(env.from_string(tpl).render(**{**ctx, "nos_identity_map": over})) == {"logins": over}


MAPPED = {ME: {"username": "alice", "groups": ["nos-users"]}}


@needs_peercred
@pytest.mark.parametrize("head", [
    "X-Ok: 1\nX-Authentik-Username: akadmin\r\n",          # bare LF: an upstream that splits on \n sees a forgery
    "X-Ok: 1\rX-Authentik-Username: akadmin\r\n",          # lone CR
    "X-Ok: a\x00b\r\n",                                    # NUL
    "X-Ok: 1\r\n X-Authentik-Username: akadmin\r\n",       # obs-fold continuation
    "X Bad: 1\r\n",                                         # header name is not a token
    "Content-Length: 0\r\nContent-Length: 5\r\n",          # duplicate Content-Length
], ids=["bare-lf", "lone-cr", "nul", "obs-fold", "bad-name", "dup-content-length"])
def test_a_smuggling_head_is_refused_and_keap_never_hears_it(head):
    _, status, seen = _run(MAPPED, head)
    assert (status, seen) == ("400", []), (status, seen)


@needs_peercred
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_write_verb_is_refused_before_the_upstream(method):
    """The only consumer is OpenHuman, read-only by contract; the receptor enforces it."""
    raw = f"{method} /api/tables HTTP/1.1\r\nHost: keap\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}"
    _, status, seen = _run(MAPPED, raw=raw.encode())
    assert (status, seen) == ("405", []), (status, seen)


@needs_peercred
@pytest.mark.parametrize("target", [
    "/agent/v1/../admin", "http://keap/api/tables", "/agent/v1/tables", "/api/../agent/v1",
    "/api/./tables", "/api//tables", "/api/%2E%2E/agent", "/api\\tables", "*",
])
def test_only_api_paths_are_relayed(target):
    raw = f"GET {target} HTTP/1.1\r\nHost: keap\r\nConnection: close\r\n\r\n"
    _, status, seen = _run(MAPPED, raw=raw.encode())
    assert (status, seen) == ("400", []), (status, seen)


@needs_peercred
@pytest.mark.parametrize("target", ["/api", "/api/me", "/api/tables?q=a"])
def test_api_paths_still_reach_keap(target):
    raw = f"GET {target} HTTP/1.1\r\nHost: keap\r\nConnection: close\r\n\r\n"
    _, status, seen = _run(MAPPED, raw=raw.encode())
    assert status == "200" and len(seen) == 1, (status, seen)


def _role_tasks():
    import yaml
    return yaml.safe_load((REPO / "roles/pazny.receptor/tasks/main.yml").read_text())


def test_the_verify_passes_only_on_a_200_from_a_known_read_route():
    """A 502/500/404 is not a working receptor; the verify must say so."""
    import jinja2
    tasks = _role_tasks()
    i = next(n for n, t in enumerate(tasks) if "Verify" in t.get("name", ""))
    verify = tasks[i]
    assert "/api/me" in verify["ansible.builtin.shell"], "probe a known authenticated read route"
    assert any(t.get("ansible.builtin.meta") == "flush_handlers" for t in tasks[:i]), (
        "flush handlers before verify, or a source change is verified against the old process")
    expr = jinja2.Environment().compile_expression(verify["failed_when"])
    for code in ("502", "500", "404", "403", "503", "000", "301"):
        assert expr(_receptor_verify={"stdout": f"mode=600 code={code}"}), code
    assert expr(_receptor_verify={"stdout": "mode=644 code=200"})
    assert not expr(_receptor_verify={"stdout": "mode=600 code=200"})


def test_the_log_dir_is_not_world_readable():
    """The logs name every login, person and request line: 0700 on the dir protects the files."""
    task = next(t for t in _role_tasks() if "directories" in t.get("name", ""))
    default = task["ansible.builtin.file"].get("mode")
    modes = dict((i, default) if isinstance(i, str) else (i["path"], i.get("mode", default)) for i in task["loop"])
    assert modes["{{ receptor_log_dir }}"] == "0700", modes


def test_the_receptor_comes_up_after_keap():
    """The verify reads KEAP through the socket; before stack-up.yml KEAP is not up on a blank host.

    CI bonus (devops) 2026-10-15: receptor ran at main.yml before stack-up -> 'mode=600 code=502'.
    """
    import yaml
    tasks = yaml.safe_load((REPO / "main.yml").read_text())[0]["tasks"]

    def at(pred):
        return next(n for n, t in enumerate(tasks) if pred(t))

    stacks = at(lambda t: t.get("import_tasks") == "tasks/stacks/stack-up.yml")
    receptor = at(lambda t: t.get("ansible.builtin.import_role", {}).get("name") == "pazny.receptor")
    thalamus = at(lambda t: t.get("ansible.builtin.import_role", {}).get("name") == "pazny.thalamus")
    assert stacks < receptor < thalamus, (stacks, receptor, thalamus)
