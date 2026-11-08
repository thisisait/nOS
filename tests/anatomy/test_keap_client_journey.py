"""One journey through the host tools that talk to KEAP: the shared keap_api helper
that carries the proxy secret or speaks through the identity outpost, the cursor
walk that reads a table to its last page, and the patience that survives a slow
KEAP without hiding a down one.

Absorbed (2026-11-08, roadmap gate-diet-role-journeys), one section each:
  test_keap_api_tools_send_proxy_secret, test_keap_api_identity_transport,
  test_keap_rows_are_paged, test_keap_slow_is_not_down.
Every assert of those files survives here with the same inputs and expectations.
"""
from __future__ import annotations

import http.server
import importlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import socketserver
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
from glob import glob

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
from keap_api import paged  # noqa: E402


# ── test_keap_api_tools_send_proxy_secret ───────────────────────────────────
# 2026-09-05: KEAP's SEC-02 proxy-trust made /api/* trust X-Authentik-* only with
# `x-keap-proxy-secret`; ~11 host tools on the 127.0.0.1:8091 publish broke at
# once (roadmap-status included). Any tool reaching KEAP's /api must route
# through tools/keap_api.py (human_headers / proxy_header).

_REPO = str(REPO)


# A host tool that reaches KEAP's human /api surface: the loopback publish AND
# an /api/ path (NOT /agent/v1 — that's the Bearer surface, not proxy-gated).
def _talks_to_keap_api(txt: str) -> bool:
    return "8091" in txt and "/api/" in txt


# Any of these means the tool routes through the shared, secret-carrying path.
_OK = ("human_headers", "proxy_header", "keap_api", "x-keap-proxy-secret")

# Files that trip the loose (8091 + /api/) trigger but do NOT call KEAP's
# identity-gated human /api — cleared with the reason. Add here ONLY when the
# /api hit is Ollama, another service, /agent (Bearer), or prose — never to
# silence a real KEAP /api caller (fix that with `from keap_api import human_headers`).
_ALLOWED = {
    "tools/estate-status.py":                 "KEAP probe is /agent/v1/health; the /api hits are bone/wing",
    "tools/local-model-bench.py":             "KEAP via /agent (Bearer); /api/generate is Ollama",
    "tools/keap-linked-data/resolve-typing.py": "/api/graph is a docstring note; live writes are /agent/v1 (Bearer)",
    "files/anatomy/scripts/keap-lint.py":     "calls /agent/v1/lint/run (Bearer); /api/lint is a docstring",
    "files/anatomy/scripts/keap-features-sync.py": "KEAP via /agent (Bearer); /api/embed is Ollama",
    "files/anatomy/scripts/keap-embed-sync.py": "KEAP via /agent (Bearer); /api/embed is Ollama",
    "tools/mcp-tables-server.py": "human /api goes through the identity outpost socket "
        "(KEAP_IDENTITY_URL, which injects the secret); the 8091 hits are the agent door (Bearer)",
}


def _candidates() -> list[str]:
    out: set[str] = set()
    for pat in ("tools/**/*.py", "files/anatomy/scripts/*.py"):
        for f in glob(os.path.join(_REPO, pat), recursive=True):
            out.add(os.path.abspath(f))
    # keap_api.py IS the helper — exempt itself.
    out.discard(os.path.join(_REPO, "tools", "keap_api.py"))
    hits = []
    for f in sorted(out):
        rel = os.path.relpath(f, _REPO)
        if rel in _ALLOWED:
            continue
        txt = open(f, encoding="utf-8", errors="ignore").read()
        if _talks_to_keap_api(txt):
            hits.append((rel, txt))
    return hits


_CASES = _candidates()


@pytest.mark.parametrize("relpath,txt", _CASES, ids=[r for r, _ in _CASES])
def test_identity_header_carries_proxy_secret(relpath, txt):
    assert any(k in txt for k in _OK), (
        f"{relpath} calls KEAP's /api on 127.0.0.1:8091 but never references the "
        f"proxy secret — it will 401 since KEAP P1. Route it through "
        f"tools/keap_api.py: `from keap_api import human_headers` and use "
        f"`human_headers(...)` for the request headers."
    )


def test_gate_sees_identity_builders():
    """A green vacuum (walker finds nothing) is not a pass."""
    assert _CASES, "no KEAP /api callers found — walker broken, not tree"


# ── test_keap_api_identity_transport ────────────────────────────────────────
# dtt-per-user-tables (2026-09-07): behind KEAP_IDENTITY_URL (a uid-identifying
# unix socket) a human-door tool sends no X-Authentik-* and no secret, and writes
# rows through the human door keyed by slug; without it nothing changes. Offline:
# a real AF_UNIX listener records what arrived.

def _short_sock() -> pathlib.Path:
    """A socket path short enough for AF_UNIX (sun_path ≤ ~104 bytes on macOS);
    pytest's tmp_path overflows it, so bind under a short /tmp dir instead."""
    return pathlib.Path(tempfile.mkdtemp(prefix="nid-", dir="/tmp")) / "s"


class _UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    allow_reuse_address = True


def _serve(sock_path: str, seen: list[dict]):
    class H(http.server.BaseHTTPRequestHandler):
        def _reply(self, code=200, payload=None):
            body = json.dumps(payload or {"success": True, "data": {"rows": []}}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            seen.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
            self._reply()

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            seen.append({"method": "POST", "path": self.path, "headers": dict(self.headers), "body": body})
            self._reply(200, {"success": True, "data": body})

        def log_message(self, *a):  # quiet
            pass

    srv = _UnixServer(sock_path, H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def _fresh_keap_api(monkeypatch, identity_url: str | None):
    if identity_url is None:
        monkeypatch.delenv("KEAP_IDENTITY_URL", raising=False)
    else:
        monkeypatch.setenv("KEAP_IDENTITY_URL", identity_url)
    monkeypatch.setenv("KEAP_PROXY_SHARED_SECRET", "not-for-the-wire")
    sys.path.insert(0, str(TOOLS))
    sys.modules.pop("keap_api", None)
    return importlib.import_module("keap_api")


def test_without_the_outpost_nothing_changes(monkeypatch):
    api = _fresh_keap_api(monkeypatch, None)
    assert api.via_identity() is False
    assert api.human_base().startswith("http://")
    h = api.human_headers()
    assert h["X-Authentik-Username"] == "akadmin" and h["x-keap-proxy-secret"] == "not-for-the-wire"


def test_behind_the_outpost_the_socket_carries_no_identity(monkeypatch):
    sock = _short_sock()
    seen: list[dict] = []
    srv = _serve(str(sock), seen)
    try:
        url = "http+unix://" + urllib.parse.quote(str(sock), safe="")
        api = _fresh_keap_api(monkeypatch, url)
        assert api.via_identity() and api.human_base() == url
        h = api.human_headers()
        assert not any(k.lower().startswith("x-authentik") for k in h), h
        assert "x-keap-proxy-secret" not in {k.lower() for k in h}, "the secret must never leave the outpost"
        # a read over the socket, through the installed opener
        with urllib.request.urlopen(urllib.request.Request(url + "/api/tables/roadmap/rows", headers=h), timeout=5) as r:
            assert r.status == 200
        assert seen and seen[-1]["path"] == "/api/tables/roadmap/rows"
        assert not any(k.lower().startswith("x-authentik") for k in seen[-1]["headers"])
        # a write goes to the HUMAN door keyed by slug — owner/tier/grants apply
        api.write_row("roadmap", {"slug": "dgx-probe", "title": "t", "status": "next"})
        w = seen[-1]
        assert w["method"] == "POST" and w["path"] == "/api/tables/roadmap/rows"
        assert w["body"] == {"id": "dgx-probe", "values": {"slug": "dgx-probe", "title": "t", "status": "next"}}
    finally:
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(sock.parent, ignore_errors=True)


def test_write_row_refuses_a_row_without_a_slug(monkeypatch):
    sock = _short_sock()
    srv = _serve(str(sock), [])
    try:
        api = _fresh_keap_api(monkeypatch, "http+unix://" + urllib.parse.quote(str(sock), safe=""))
        try:
            api.write_row("roadmap", {"title": "no key"})
        except RuntimeError as e:
            assert "slug" in str(e)
        else:
            raise AssertionError("a slug-less row must be refused — the human door would mint a duplicate")
    finally:
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(sock.parent, ignore_errors=True)


# ── test_keap_rows_are_paged ────────────────────────────────────────────────
# /rows caps a page at 500 and returns `nextCursor`. On 2026-10-03 the roadmap
# held 508 rows, every reader saw 500, and roadmap-seed would have re-inserted
# the other eight. keap_api.paged() walks the cursor; no tool stops at page one.

def test_paged_follows_the_cursor_to_the_end():
    pages = {None: ([1, 2], "2"), "2": ([3, 4], "4"), "4": ([5], None)}

    def fetch(url):
        cur = re.search(r"cursor=([^&]+)", url)
        rows, nxt = pages[cur.group(1) if cur else None]
        return {"success": True, "data": {"rows": rows, "nextCursor": nxt}}

    out = paged(fetch, "http://keap/api/tables/t/rows")
    assert out["data"]["rows"] == [1, 2, 3, 4, 5]
    assert "nextCursor" not in out["data"]


def test_no_tool_reads_a_table_as_one_page():
    bad = []
    for p in TOOLS.glob("*.py"):
        text = p.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            # a page-one read is fine only in a file that walks nextCursor itself
            if re.search(r"/rows\?limit=500", line) and "paged" not in line and "nextCursor" not in text:
                bad.append(f"{p.relative_to(REPO)}:{i}")
    assert not bad, f"read past page one with keap_api.paged(): {bad}"


# ── test_keap_slow_is_not_down ──────────────────────────────────────────────
# 2026-09-23: a pipeline cycle died "KEAP unreadable (timed out)" while a 14.9 GB
# qwen3:14b sat resident (KEAP API ~0.09s -> ~25s); every digest tool had a flat
# 15s deadline. One retry at double the deadline rescues a loaded host and must
# not rescue a down one.

_spec = importlib.util.spec_from_file_location("digest_absorb", TOOLS / "digest_absorb.py")
DA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DA)


class _Resp:
    def read(self):
        return b"{}"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_slow_call_is_retried_once_with_a_longer_deadline(monkeypatch):
    seen: list[float] = []

    def fake(req, timeout=None):
        seen.append(timeout)
        if len(seen) == 1:
            raise TimeoutError("too slow")
        return _Resp()

    monkeypatch.setattr(DA.urllib.request, "urlopen", fake)
    with DA._open(object()):
        pass
    assert len(seen) == 2, "a slow KEAP was not retried"
    assert seen[1] == seen[0] * 2, "the retry did not lengthen the deadline"


def test_a_down_keap_still_raises(monkeypatch):
    """The defect this must NOT introduce: patience that never gives up."""
    calls = []

    def always_slow(req, timeout=None):
        calls.append(timeout)
        raise TimeoutError("down")

    monkeypatch.setattr(DA.urllib.request, "urlopen", always_slow)
    with pytest.raises(TimeoutError):
        DA._open(object())
    assert len(calls) == 2, "it must try exactly twice, then surface the timeout"


def test_the_deadline_is_tunable_for_a_loaded_host(monkeypatch):
    monkeypatch.setenv("NOS_KEAP_TIMEOUT_S", "60")
    spec = importlib.util.spec_from_file_location("da2", TOOLS / "digest_absorb.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._TIMEOUT_S == 60


def test_every_digest_call_goes_through_it():
    """A call site left on a flat urlopen would fail on exactly the host this
    exists for, and nothing would say so."""
    src = (TOOLS / "digest_absorb.py").read_text(encoding="utf-8")
    body = src.split("def _open(", 1)[1].split("\ndef ", 1)[0]
    outside = src.replace(body, "")
    assert "urlopen(req" not in outside, (
        "a KEAP call still bypasses _open — it will fail while a model is warm")
