"""Wing's hub probes a service with HEAD; the device gateway answered it 501 and its card
read down while the gateway ran (the Studio's journeys, 2026-11-02). Runs the real
gateway on a free port: HEAD /health is 200, HEAD elsewhere is not a 5xx (Wing counts
2xx-4xx as up), GET /health is unchanged."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

GATEWAY = Path(__file__).resolve().parents[2] / "files/anatomy/device-gateway/gateway.py"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _code(method: str, url: str) -> int:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_the_gateway_answers_head_as_wing_probes():
    port = _free_port()
    env = {**os.environ, "GATEWAY_PORT": str(port), "GATEWAY_TOKEN": "fake-token-for-test"}
    proc = subprocess.Popen([sys.executable, str(GATEWAY)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                _code("GET", base + "/health")
                break
            except OSError:
                time.sleep(0.05)
        assert _code("HEAD", base + "/health") == 200
        assert _code("HEAD", base + "/") < 500, "a 5xx to HEAD reads the gateway down in Wing's hub"
        assert _code("GET", base + "/health") == 200
    finally:
        proc.terminate()
        proc.wait(5)
