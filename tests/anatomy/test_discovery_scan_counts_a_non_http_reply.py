"""Gate — discovery-scan's healthy-but-unreachable probe asks about TRANSPORT.

Measured 2026-10-07: `smtp_stalwart is healthy and answers nothing on
127.0.0.1:25`. Stalwart answered — a `220 ... ESMTP` banner — but the probe
speaks HTTP, `http.client` raised BadStatusLine on the banner, and the
`except Exception` arm filed the reply as silence. The row's port_var IS the
SMTP port (manifest: "25 = MTA"), so the pair itself is honest; the reader
misread the answer. Any bytes back prove the port forward lands on a listener,
which is the only thing this probe claims to know. An empty close
(RemoteDisconnected) is still a finding.

Measured 2026-10-08 through the real opener, 60 runs per shape: a banner raises
BadStatusLine 60/60; close-before-read raises ConnectionResetError 51 or
RemoteDisconnected 9 (a race on whether the FIN or the RST lands first), both
RAW — urllib wraps only errors from h.request, not from getresponse;
read-then-close raises RemoteDisconnected 60/60; accept-and-never-send raises
TimeoutError 25 or URLError(timeout) 35. Only BadStatusLine proper may count
as an answer; every other shape is the finding. RemoteDisconnected is a
SUBCLASS of BadStatusLine, so `except BadStatusLine` alone swallows the empty
close 9 times in 60. The empty-close fake below reads the request before
closing — the 60/60 shape — so the test is deterministic (20/20 in a loop)
and the race lives in the probe, where it belongs.
"""
from __future__ import annotations

import importlib.util
import pathlib
import socketserver
import sys
import threading

REPO = pathlib.Path(__file__).resolve().parents[2]
MODPATH = REPO / "tools" / "discovery-scan.py"


def _load():
    spec = importlib.util.spec_from_file_location("discovery_scan_non_http", MODPATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["discovery_scan_non_http"] = mod
    spec.loader.exec_module(mod)
    return mod


class _Banner(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(b"220 mail.example ESMTP Stalwart\r\n")
        self.request.recv(64)


class _EmptyClose(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.recv(4096)  # take the request, so the close is an EOF, not a RST
        return  # close without a byte: the paperclip shape


def _probe(mod, tmp_path, handler, monkeypatch):
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    (tmp_path / "state").mkdir()
    (tmp_path / "state/manifest.yml").write_text(
        "services:\n  - id: smtp_stalwart\n    domain_var: stalwart_domain\n"
        "    port_var: stalwart_port_smtp\n", encoding="utf-8")
    monkeypatch.setattr(mod, "REPO", tmp_path)
    monkeypatch.setattr(mod, "loopback_port", lambda _v: str(port))
    monkeypatch.setattr(mod, "container_for", lambda *_a: ("smtp_stalwart", "img"))
    monkeypatch.setattr(mod.subprocess, "run", lambda *_a, **_k: type(
        "R", (), {"stdout": "smtp_stalwart\n"})())
    res = mod.ScanResult()
    try:
        mod.probe_healthy_but_unreachable({}, res)
    finally:
        srv.shutdown()
        srv.server_close()
    return res


def test_an_smtp_banner_is_an_answer(tmp_path, monkeypatch):
    res = _probe(_load(), tmp_path, _Banner, monkeypatch)
    assert "obs-healthy-unreachable-smtp-stalwart" in res.judged
    assert res.findings == [], [f.title for f in res.findings]


def test_an_empty_close_is_still_silence(tmp_path, monkeypatch):
    res = _probe(_load(), tmp_path, _EmptyClose, monkeypatch)
    assert [f.slug for f in res.findings] == ["obs-healthy-unreachable-smtp-stalwart"]
